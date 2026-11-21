"""MikroTik REST API collector.

Polls mANTBox and NetMetal for live registration-table and system statistics.

Noise floor:
- RouterOS /interface/wifi/registration-table does not currently expose a
  documented noise-floor field for the user's Wi-Fi 6 setup.
- A one-shot /interface/wifi/frequency-scan can return `nf` (dBm), but MikroTik
  documents that this scan disconnects associated clients.
- Therefore, noise-floor scanning is NEVER started by the background polling
  loop. An operator must explicitly call request_noise_floor_scan(), after
  making sure the rover is stationary and the scanned router has an independent
  wired/out-of-band management path.

The one-shot scan result is retained as a timestamped snapshot and included in
radio_link. SNR is calculated only when the snapshot contains the router's
current channel and is still within the configured maximum age. It is labelled
as an estimate derived from a scan snapshot, not a continuous live SNR value.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from services.telemetry_service import telemetry_service

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

_RATE_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>gbps|gbit/s|mbps|mbit/s|kbps|kbit/s|bps|bit/s)",
    re.IGNORECASE,
)
_RATE_MULTIPLIERS = {
    "bps": 1,
    "bit/s": 1,
    "kbps": 1_000,
    "kbit/s": 1_000,
    "mbps": 1_000_000,
    "mbit/s": 1_000_000,
    "gbps": 1_000_000_000,
    "gbit/s": 1_000_000_000,
}

# Runtime references are populated by run_mikrotik_collector(). They allow a
# FastAPI route to trigger a one-shot scan without creating a second client.
_ACTIVE_CLIENTS: dict[str, httpx.AsyncClient] = {}
_ACTIVE_CONFIGS: dict[str, "RouterConfig"] = {}
_ROUTER_LOCKS: dict[str, asyncio.Lock] = {}
_NOISE_FLOOR_SNAPSHOTS: dict[str, dict[str, Any]] = {}
_NOISE_SCAN_STATUS: dict[str, dict[str, Any]] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_file() -> None:
    """Load simple KEY=VALUE settings without adding a dependency."""
    if not ENV_FILE.is_file():
        logger.warning("MikroTik .env file not found: %s", ENV_FILE)
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class RouterConfig:
    name: str
    ip: str
    username: str
    password: str
    ca_certificate: Path
    wifi_interface: str


def make_router_config(prefix: str, name: str, default_ip: str) -> RouterConfig | None:
    ip = os.getenv(f"{prefix}_IP", default_ip).strip()
    username = os.getenv(f"{prefix}_USERNAME", "").strip()
    password = os.getenv(f"{prefix}_PASSWORD", "")
    cert_setting = os.getenv(f"{prefix}_CA_CERT", "").strip()
    wifi_interface = os.getenv(f"{prefix}_WIFI_INTERFACE", "5ghzmikro").strip()

    if not username or not password or not cert_setting:
        logger.error("%s credentials or CA certificate setting is missing.", name)
        return None

    cert_path = Path(cert_setting)
    if not cert_path.is_absolute():
        cert_path = BACKEND_DIR / cert_path
    if not cert_path.is_file():
        logger.error("%s CA certificate not found: %s", name, cert_path)
        return None

    return RouterConfig(
        name=name,
        ip=ip,
        username=username,
        password=password,
        ca_certificate=cert_path,
        wifi_interface=wifi_interface,
    )


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    value_text = str(value).strip().lower()
    if value_text in ("true", "yes", "1"):
        return True
    if value_text in ("false", "no", "0"):
        return False
    return None


def parse_rate_bps(value: Any) -> int | None:
    """Convert RouterOS strings such as 866.7Mbps into bits/second."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    match = _RATE_PATTERN.search(text)
    if match:
        return int(float(match.group("number")) * _RATE_MULTIPLIERS[match.group("unit").lower()])
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_frequency_mhz(value: Any) -> int | None:
    """Parse monitor channel strings such as '5180/ax' into 5180."""
    if value is None:
        return None
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value))
    return int(match.group(1)) if match else None


def normalize_system(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    return {
        "board_name": data.get("board-name"),
        "version": data.get("version"),
        "uptime": data.get("uptime"),
        "cpu_load_percent": to_int(data.get("cpu-load")),
        "free_memory_bytes": to_int(data.get("free-memory")),
        "total_memory_bytes": to_int(data.get("total-memory")),
    }


def normalize_wireless(data: Any) -> dict[str, Any]:
    """Normalize this router's received signal from its registered peer."""
    records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    records = [item for item in records if isinstance(item, dict)]

    peer = next(
        (item for item in records if to_bool(item.get("authorized")) is True),
        records[0] if records else {},
    )
    authorized = to_bool(peer.get("authorized"))

    if not records:
        link_status = "disconnected"
    elif authorized is True:
        link_status = "connected"
    else:
        link_status = "unauthorized"

    signal_dbm = to_int(peer.get("signal"))
    # Optional aliases are retained for RouterOS builds that expose them.
    # On the current Wi-Fi 6 registration-table output these are normally absent.
    noise_floor_dbm = to_int(
        peer.get("noise-floor", peer.get("noise_floor", peer.get("nf")))
    )
    snr_db = to_int(
        peer.get("signal-to-noise", peer.get("signal_to_noise", peer.get("snr")))
    )
    if snr_db is None and signal_dbm is not None and noise_floor_dbm is not None:
        snr_db = signal_dbm - noise_floor_dbm

    tx_rate_raw = peer.get("tx-rate")
    rx_rate_raw = peer.get("rx-rate")

    return {
        "link_status": link_status,
        "interface": peer.get("interface"),
        "ssid": peer.get("ssid"),
        "peer_mac_address": peer.get("mac-address"),
        "authorized": authorized,
        "signal_dbm": signal_dbm,
        "noise_floor_dbm": noise_floor_dbm,
        "snr_db": snr_db,
        "snr_is_estimated": False if snr_db is not None else None,
        "noise_floor_source": "registration_table" if noise_floor_dbm is not None else None,
        "tx_rate_bps": parse_rate_bps(tx_rate_raw),
        "rx_rate_bps": parse_rate_bps(rx_rate_raw),
        "tx_rate_raw": tx_rate_raw,
        "rx_rate_raw": rx_rate_raw,
        "tx_throughput_bps": to_int(peer.get("tx-bits-per-second")),
        "rx_throughput_bps": to_int(peer.get("rx-bits-per-second")),
        "last_activity": peer.get("last-activity"),
        "uptime": peer.get("uptime"),
    }


async def fetch_json(
    client: httpx.AsyncClient,
    endpoint: str,
    fields: str | None = None,
) -> Any:
    params = {".proplist": fields} if fields else None
    response = await client.get(f"/rest/{endpoint}", params=params)
    response.raise_for_status()
    return response.json()


async def post_command(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict[str, Any],
    timeout_s: float | None = None,
) -> Any:
    response = await client.post(
        f"/rest/{endpoint}",
        json=payload,
        timeout=timeout_s,
    )
    response.raise_for_status()
    if not response.content:
        return []
    return response.json()


async def poll_system(client: httpx.AsyncClient) -> dict[str, Any]:
    data = await fetch_json(
        client,
        "system/resource",
        "board-name,version,uptime,cpu-load,free-memory,total-memory",
    )
    return normalize_system(data)


async def poll_wireless(
    client: httpx.AsyncClient,
    config: RouterConfig,
) -> dict[str, Any]:
    # Do not specify .proplist here: keep any extra fields a future RouterOS
    # version may add, including possible noise/SNR aliases.
    data = await fetch_json(client, "interface/wifi/registration-table")
    normalized = normalize_wireless(data)
    normalized["observed_at"] = utc_now_iso()
    return normalized


async def poll_wifi_monitor(
    client: httpx.AsyncClient,
    config: RouterConfig,
) -> dict[str, Any]:
    """Read the current radio channel at a slower cadence (not at 10 Hz)."""
    data = await post_command(
        client,
        "interface/wifi/monitor",
        {"numbers": config.wifi_interface, "once": ""},
    )
    if isinstance(data, list):
        record = next((item for item in data if isinstance(item, dict)), {})
    elif isinstance(data, dict):
        record = data
    else:
        record = {}

    return {
        "state": record.get("state"),
        "channel": record.get("channel"),
        "channel_mhz": parse_frequency_mhz(record.get("channel")),
        "ap_address": record.get("ap-address"),
        "tx_power_dbm": to_int(record.get("tx-power")),
        "observed_at": utc_now_iso(),
    }


def _parse_scan_frequencies(value: str | list[int] | tuple[int, ...] | None) -> list[int]:
    if value is None:
        value = os.getenv("MIKROTIK_NOISE_SCAN_FREQUENCIES", "5180,5200,5220,5240")
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value.strip())
        values = [to_int(part) for part in parts if part]
    else:
        values = [to_int(part) for part in value]
    frequencies = sorted({item for item in values if item is not None and 2000 <= item <= 7000})
    if not frequencies:
        raise ValueError("No valid scan frequencies supplied.")
    return frequencies


def _normalize_frequency_scan(data: Any, config: RouterConfig) -> dict[str, Any]:
    records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    measurements: list[dict[str, Any]] = []

    for item in records:
        if not isinstance(item, dict):
            continue
        frequency = to_int(item.get("channel", item.get("frequency")))
        nf = to_int(item.get("nf"))
        if frequency is None or nf is None:
            continue
        measurements.append({
            "frequency_mhz": frequency,
            "noise_floor_dbm": nf,
            "channel_load_percent": to_int(item.get("load")),
            "networks": to_int(item.get("networks")),
            "max_signal_dbm": to_int(item.get("max-signal")),
            "min_signal_dbm": to_int(item.get("min-signal")),
            "primary": to_bool(item.get("primary")),
            "secondary": to_bool(item.get("secondary")),
        })

    return {
        "router": config.name,
        "interface": config.wifi_interface,
        "source": "RouterOS /interface/wifi/frequency-scan",
        "measured_at": utc_now_iso(),
        "measurements": sorted(measurements, key=lambda row: row["frequency_mhz"]),
    }


async def request_noise_floor_scan(
    router_name: str,
    frequencies_mhz: str | list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Trigger one disruptive frequency scan and store its NF snapshot.

    Call this from a deliberate operator-only FastAPI endpoint. It is disabled
    unless MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN=true is set in backend/.env.
    The caller must ensure the rover is stationary and the backend has a wired
    or other out-of-band route to the router being scanned. The frequency scan
    disconnects Wi-Fi clients / a station from its AP.
    """
    allowed = os.getenv("MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN", "false").strip().lower()
    if allowed not in ("true", "1", "yes"):
        raise RuntimeError(
            "Noise-floor scan is disabled. Set "
            "MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN=true only for a planned, "
            "stationary maintenance test with independent management access."
        )

    key = router_name.strip().lower()
    if key not in _ACTIVE_CLIENTS or key not in _ACTIVE_CONFIGS:
        raise RuntimeError("MikroTik collector is not running or router name is invalid.")

    config = _ACTIVE_CONFIGS[key]
    client = _ACTIVE_CLIENTS[key]
    lock = _ROUTER_LOCKS[key]
    frequencies = _parse_scan_frequencies(frequencies_mhz)
    status = {
        "status": "scanning",
        "requested_at": utc_now_iso(),
        "interface": config.wifi_interface,
        "frequencies_mhz": frequencies,
        "warning": "This operation temporarily disconnects Wi-Fi clients.",
    }
    _NOISE_SCAN_STATUS[key] = status

    logger.warning(
        "Starting operator-requested DISRUPTIVE noise-floor scan on %s (%s), frequencies=%s",
        config.name,
        config.wifi_interface,
        frequencies,
    )

    try:
        # Prevent the normal poller from issuing requests to this router while
        # its radio is being switched into frequency-scan mode.
        async with lock:
            timeout_s = max(30.0, float(os.getenv("MIKROTIK_NOISE_SCAN_TIMEOUT_S", "60")))
            result = await post_command(
                client,
                "interface/wifi/frequency-scan",
                {
                    "number": config.wifi_interface,
                    "frequency": ",".join(str(item) for item in frequencies),
                    "rounds": "1",
                },
                timeout_s=timeout_s,
            )

        snapshot = _normalize_frequency_scan(result, config)
        if not snapshot["measurements"]:
            raise RuntimeError(
                "RouterOS completed the scan but returned no rows containing both channel and nf. "
                f"Raw response type: {type(result).__name__}"
            )

        _NOISE_FLOOR_SNAPSHOTS[key] = snapshot
        _NOISE_SCAN_STATUS[key] = {
            "status": "complete",
            "completed_at": snapshot["measured_at"],
            "interface": config.wifi_interface,
            "frequencies_mhz": frequencies,
            "measurement_count": len(snapshot["measurements"]),
        }
        logger.info(
            "%s noise-floor scan completed: %d measurement(s)",
            config.name,
            len(snapshot["measurements"]),
        )
        return snapshot

    except Exception as exc:
        _NOISE_SCAN_STATUS[key] = {
            "status": "failed",
            "failed_at": utc_now_iso(),
            "interface": config.wifi_interface,
            "frequencies_mhz": frequencies,
            "error": f"{type(exc).__name__}: {exc}",
        }
        logger.exception("Noise-floor scan failed on %s", config.name)
        raise


def _age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except (TypeError, ValueError):
        return None


def build_router_payload(
    config: RouterConfig,
    state: dict[str, Any],
) -> dict[str, Any]:
    system_ok = state["system_ok"]
    wireless_ok = state["wireless_ok"]
    if system_ok and wireless_ok:
        api_status = "online"
    elif system_ok or wireless_ok:
        api_status = "partial"
    else:
        api_status = "offline"

    wireless = dict(state["wireless"])
    monitor = state["radio_monitor"]
    snapshot = _NOISE_FLOOR_SNAPSHOTS.get(config.name.lower())
    scan_status = _NOISE_SCAN_STATUS.get(config.name.lower(), {"status": "not_requested"})

    # Use a scan value only for the channel the radio is currently using.
    # This prevents applying the 5180 MHz noise floor to a 5200 MHz link after
    # frequency hopping.
    current_channel = monitor.get("channel_mhz")
    max_age_s = max(1.0, float(os.getenv("MIKROTIK_NOISE_SNAPSHOT_MAX_AGE_S", "900")))
    if snapshot:
        snapshot_age = _age_seconds(snapshot.get("measured_at"))
        measurement = next(
            (
                row for row in snapshot.get("measurements", [])
                if row.get("frequency_mhz") == current_channel
            ),
            None,
        )
        wireless["noise_floor_scan"] = snapshot
        wireless["noise_floor_scan_status"] = scan_status
        wireless["noise_floor_age_s"] = round(snapshot_age, 1) if snapshot_age is not None else None

        if measurement and snapshot_age is not None and snapshot_age <= max_age_s:
            noise_floor_dbm = measurement["noise_floor_dbm"]
            wireless["noise_floor_dbm"] = noise_floor_dbm
            wireless["noise_floor_source"] = "frequency_scan_snapshot"
            wireless["noise_floor_measured_at"] = snapshot.get("measured_at")
            wireless["noise_floor_frequency_mhz"] = current_channel

            signal_dbm = to_int(wireless.get("signal_dbm"))
            if signal_dbm is not None:
                wireless["snr_db"] = signal_dbm - noise_floor_dbm
                wireless["snr_source"] = "estimated_from_frequency_scan_snapshot"
                wireless["snr_is_estimated"] = True
            else:
                wireless["snr_db"] = None
                wireless["snr_source"] = None
                wireless["snr_is_estimated"] = None
        elif wireless.get("noise_floor_source") != "registration_table":
            wireless["noise_floor_dbm"] = None
            wireless["noise_floor_source"] = "stale_or_channel_mismatch" if measurement else "no_measurement_for_current_channel"
            wireless["noise_floor_measured_at"] = snapshot.get("measured_at")
            wireless["noise_floor_frequency_mhz"] = None
            wireless["snr_db"] = None
            wireless["snr_source"] = None
            wireless["snr_is_estimated"] = None
    else:
        wireless["noise_floor_scan"] = None
        wireless["noise_floor_scan_status"] = scan_status
        wireless["noise_floor_age_s"] = None
        if wireless.get("noise_floor_source") != "registration_table":
            wireless["noise_floor_dbm"] = None
            wireless["noise_floor_source"] = "not_measured"
            wireless["noise_floor_measured_at"] = None
            wireless["noise_floor_frequency_mhz"] = None
            wireless["snr_db"] = None
            wireless["snr_source"] = None
            wireless["snr_is_estimated"] = None

    wireless["current_channel_mhz"] = current_channel

    return {
        "name": config.name,
        "ip": config.ip,
        "api_status": api_status,
        "last_updated": wireless.get("observed_at") or state["system_updated_at"],
        "system_updated_at": state["system_updated_at"],
        "system": state["system"],
        "radio_monitor": monitor,
        "wireless": wireless,
        "errors": {
            "system": state["system_error"],
            "wireless": state["wireless_error"],
            "radio_monitor": state["radio_monitor_error"],
        },
    }


async def run_mikrotik_collector() -> None:
    """Background task: quick wireless polling and slower system polling."""
    load_env_file()

    enabled = os.getenv("MIKROTIK_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    if not enabled:
        logger.info("MikroTik collector is disabled.")
        return

    try:
        legacy_interval = os.getenv("MIKROTIK_POLL_INTERVAL_S", "1")
        radio_interval = max(0.1, float(os.getenv("MIKROTIK_RADIO_POLL_INTERVAL_S", legacy_interval)))
        system_interval = max(1.0, float(os.getenv("MIKROTIK_SYSTEM_POLL_INTERVAL_S", "5")))
        request_timeout = max(0.2, float(os.getenv("MIKROTIK_REQUEST_TIMEOUT_S", "1")))
    except ValueError:
        logger.exception("Invalid MikroTik polling configuration.")
        return

    configs = [
        make_router_config("MANTBOX", "mANTBox", "192.168.88.1"),
        make_router_config("NETMETAL", "NetMetal", "192.168.88.2"),
    ]
    configs = [config for config in configs if config is not None]
    if not configs:
        logger.error("No valid MikroTik router configurations found.")
        return

    clients: dict[str, httpx.AsyncClient] = {}
    states: dict[str, dict[str, Any]] = {}
    last_error_log: dict[str, float] = {}

    # Reset public runtime registries each time the collector starts.
    _ACTIVE_CLIENTS.clear()
    _ACTIVE_CONFIGS.clear()
    _ROUTER_LOCKS.clear()
    _NOISE_FLOOR_SNAPSHOTS.clear()
    _NOISE_SCAN_STATUS.clear()

    for config in configs:
        key = config.name.lower()
        client = httpx.AsyncClient(
            base_url=f"https://{config.ip}",
            auth=(config.username, config.password),
            verify=str(config.ca_certificate),
            timeout=httpx.Timeout(request_timeout, connect=min(request_timeout, 0.5)),
        )
        clients[key] = client
        _ACTIVE_CLIENTS[key] = client
        _ACTIVE_CONFIGS[key] = config
        _ROUTER_LOCKS[key] = asyncio.Lock()
        _NOISE_SCAN_STATUS[key] = {"status": "not_requested"}
        states[key] = {
            "system": {},
            "wireless": {
                "link_status": "unknown",
                "signal_dbm": None,
                "noise_floor_dbm": None,
                "snr_db": None,
                "observed_at": None,
            },
            "radio_monitor": {},
            "system_ok": False,
            "wireless_ok": False,
            "system_error": "No system sample received yet",
            "wireless_error": "No wireless sample received yet",
            "radio_monitor_error": "No radio monitor sample received yet",
            "system_updated_at": None,
        }

    async def update_system(config: RouterConfig) -> None:
        key = config.name.lower()
        state = states[key]
        try:
            state["system"] = await poll_system(clients[key])
            state["system_ok"] = True
            state["system_error"] = None
            state["system_updated_at"] = utc_now_iso()
        except Exception as exc:
            state["system"] = {}
            state["system_ok"] = False
            state["system_error"] = f"{type(exc).__name__}: {exc}"
            state["system_updated_at"] = None
            logger.debug("%s system poll failed: %s", config.name, exc)

    async def update_wireless(config: RouterConfig) -> None:
        key = config.name.lower()
        state = states[key]
        try:
            async with _ROUTER_LOCKS[key]:
                state["wireless"] = await poll_wireless(clients[key], config)
            state["wireless_ok"] = True
            state["wireless_error"] = None
        except Exception as exc:
            state["wireless"] = {
                "link_status": "unknown",
                "interface": config.wifi_interface,
                "peer_mac_address": None,
                "authorized": None,
                "signal_dbm": None,
                "noise_floor_dbm": None,
                "snr_db": None,
                "tx_rate_bps": None,
                "rx_rate_bps": None,
                "tx_throughput_bps": None,
                "rx_throughput_bps": None,
                "observed_at": None,
            }
            state["wireless_ok"] = False
            state["wireless_error"] = f"{type(exc).__name__}: {exc}"
            now = asyncio.get_running_loop().time()
            previous_log = last_error_log.get(key, 0.0)
            if now - previous_log >= 5.0:
                logger.warning("%s wireless poll failed: %s", config.name, exc)
                last_error_log[key] = now

    async def update_radio_monitor(config: RouterConfig) -> None:
        key = config.name.lower()
        state = states[key]
        try:
            async with _ROUTER_LOCKS[key]:
                state["radio_monitor"] = await poll_wifi_monitor(clients[key], config)
            state["radio_monitor_error"] = None
        except Exception as exc:
            # Keep the last successful channel for diagnostics, but note the
            # failed refresh explicitly. Do not synthesize a new channel.
            state["radio_monitor_error"] = f"{type(exc).__name__}: {exc}"
            logger.debug("%s Wi-Fi monitor poll failed: %s", config.name, exc)

    logger.info(
        "MikroTik collector started for %s; radio target=%.0f ms; system/monitor interval=%.1f s; disruptive NF scan is manual-only",
        ", ".join(config.name for config in configs),
        radio_interval * 1000,
        system_interval,
    )

    loop = asyncio.get_running_loop()
    next_system_poll = 0.0
    last_wireless_poll_started: float | None = None

    try:
        while True:
            cycle_started = loop.time()
            if cycle_started >= next_system_poll:
                await asyncio.gather(
                    *(update_system(config) for config in configs),
                    *(update_radio_monitor(config) for config in configs),
                )
                next_system_poll = loop.time() + system_interval

            wireless_poll_started = loop.time()
            actual_interval_ms = (
                None if last_wireless_poll_started is None
                else (wireless_poll_started - last_wireless_poll_started) * 1000.0
            )
            last_wireless_poll_started = wireless_poll_started

            await asyncio.gather(*(update_wireless(config) for config in configs))
            wireless_poll_duration_ms = (loop.time() - wireless_poll_started) * 1000.0

            routers = {
                config.name.lower(): build_router_payload(config, states[config.name.lower()])
                for config in configs
            }
            telemetry_service.update_custom({
                "radio_link": {
                    "updated_at": utc_now_iso(),
                    "poll_interval_s": radio_interval,
                    "sample_interval_ms": radio_interval * 1000.0,
                    "system_poll_interval_s": system_interval,
                    "poll_duration_ms": round(wireless_poll_duration_ms, 1),
                    "actual_interval_ms": round(actual_interval_ms, 1) if actual_interval_ms is not None else None,
                    "routers": routers,
                }
            })

            elapsed = loop.time() - cycle_started
            await asyncio.sleep(max(0.0, radio_interval - elapsed))

    finally:
        for client in clients.values():
            await client.aclose()
        _ACTIVE_CLIENTS.clear()
        _ACTIVE_CONFIGS.clear()
        _ROUTER_LOCKS.clear()
        logger.info("MikroTik collector stopped.")
