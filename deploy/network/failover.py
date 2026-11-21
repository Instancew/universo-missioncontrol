#!/usr/bin/env python3
"""Local-router controller. Standard library only; TLS verification always enabled.

Run one instance on each wired endpoint: Jetson->NetMetal, base->mANTBox.
Neither controller depends on reaching the opposite router to change local routes.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import ssl
import time
import urllib.request

LOG = logging.getLogger("failover")


@dataclass(frozen=True)
class Sample:
    loss: float = 100
    latency_ms: float = math.inf
    valid: bool = False
    associated: bool | None = None
    rssi: str | None = None
    tx_rate: str | None = None
    rx_rate: str | None = None


@dataclass(frozen=True)
class Thresholds:
    max_loss: float = 20
    max_latency_ms: float = 100
    recover_loss: float = 5
    recover_latency_ms: float = 60
    outage_seconds: float = 2
    degrade_seconds: float = 5
    recovery_seconds: float = 20
    backup_ready_seconds: float = 1
    max_gap_seconds: float = 5


class Policy:
    def __init__(self, active="5", thresholds=None):
        self.active = active
        self.t = thresholds or Thresholds()
        self.since = {}
        self.previous = None

    def usable(self, sample, recover=False):
        return (sample.valid and math.isfinite(sample.latency_ms) and
                sample.loss <= (self.t.recover_loss if recover else self.t.max_loss) and
                sample.latency_ms <= (self.t.recover_latency_ms if recover else self.t.max_latency_ms))

    def held(self, name, condition, now, seconds):
        if not condition:
            self.since.pop(name, None)
            return False
        return now - self.since.setdefault(name, now) >= seconds

    def decide(self, primary, backup, now, video_fresh=None):
        if self.previous is not None and (now < self.previous or now - self.previous > self.t.max_gap_seconds):
            self.since.clear()  # Stale measurements cannot satisfy hysteresis.
        self.previous = now
        p, b = self.usable(primary), self.usable(backup)
        ready = self.held("backup", b, now, self.t.backup_ready_seconds)
        down = self.held("down", primary.valid and primary.loss >= 100, now, self.t.outage_seconds)
        weak = self.held("weak", primary.valid and not p, now, self.t.degrade_seconds)
        recovered = self.held("recovered", self.usable(primary, True), now, self.t.recovery_seconds)
        backup_down = self.held("backup_down", backup.valid and not b, now, self.t.outage_seconds)
        if self.active == "5" and ready and (down or weak):
            return "24", "confirmed 5 GHz outage" if down else "sustained 5 GHz loss/latency degradation"
        if self.active == "24" and p and (recovered or backup_down):
            return "5", "5 GHz stable recovery" if recovered else "backup unusable; healthy 5 GHz emergency return"
        if video_fresh is False and (p if self.active == "5" else b):
            return self.active, "video problem; network healthy; no band change"
        if not primary.valid or not backup.valid:
            return self.active, "probe unavailable; do not infer RF outage from controller/API error"
        if not p and not b:
            return self.active, "both paths unhealthy; hold route and alert"
        return self.active, "hold; monitoring both bands"


def duration_ms(value):
    text = str(value)
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|us|ns|s)", text)
    if not parts or "".join(n + unit for n, unit in parts) != text:
        raise ValueError("Unknown RouterOS duration format")
    return sum(float(n) * {"s": 1000, "ms": 1, "us": .001, "ns": .000001}[unit] for n, unit in parts)


def parse_ping(rows, target, count):
    # Require the completed sequence, not just any successful response.
    if not isinstance(rows, list) or not rows:
        return Sample()
    final = rows[-1]
    try:
        sent, received = int(final["sent"]), int(final["received"])
        if sent != count or not 0 <= received <= sent:
            return Sample()
        if any(row.get("host") != target for row in rows if "time" in row):
            return Sample()
        return Sample(loss=100 * (sent - received) / sent,
                      latency_ms=duration_ms(final["avg-rtt"]) if received else math.inf, valid=True)
    except (KeyError, TypeError, ValueError):
        return Sample()


class Router:
    def __init__(self, config):
        self.config = config
        self.url = config["router_url"].rstrip("/")
        if not self.url.startswith("https://"):
            raise ValueError("Router REST URL must use HTTPS")
        self.context = ssl.create_default_context(cafile=os.environ["ROUTER_CA_FILE"])
        credentials = f'{os.environ["ROUTER_USER"]}:{os.environ["ROUTER_PASSWORD"]}'
        self.auth = "Basic " + base64.b64encode(credentials.encode()).decode()

    def request(self, path, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + "/rest/" + path, data=data, method=method,
            headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, context=self.context, timeout=3) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def probe(self, band):
        conf = self.config["bands"][band]
        try:
            rows = self.request("ping", {"address": conf["peer"], "src-address": conf["source"],
                # Current RouterOS accepts vrf, not a policy routing-table argument.
                # Peer-specific lookup-only rules in both CPE templates select the table.
                "interface": conf["interface"], "count": "5", "interval": "100ms"})
            return parse_ping(rows, conf["peer"], 5)
        except Exception as exc:
            LOG.warning("band=%s probe API unavailable (%s)", band, type(exc).__name__)
            return Sample()

    def diagnostics(self):
        try:
            rows = self.request("interface/wifi/registration-table")
            result = {}
            for band, conf in self.config["bands"].items():
                # Filter peer MAC: mANTBox may also have unrelated Wi-Fi clients.
                peers = [row for row in rows if row.get("interface") == conf["interface"] and
                         row.get("mac-address", "").upper() == conf["peer_mac"].upper()]
                row = peers[0] if peers else {}
                result[band] = {"associated": bool(peers), "rssi": row.get("signal"),
                                "tx_rate": row.get("tx-rate"), "rx_rate": row.get("rx-rate")}
            return result
        except Exception as exc:
            LOG.warning("radio diagnostics unavailable (%s)", type(exc).__name__)
            return {}

    def routes(self):
        rows = self.request("ip/route")
        found = {}
        for band, conf in self.config["bands"].items():
            matches = [row for row in rows if row.get("comment") == conf["route_comment"]]
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one owned route per band")
            row = matches[0]
            if (row.get("dst-address") != self.config["remote_lan"] or
                row.get("gateway") != f'{conf["peer"]}%{conf["interface"]}' or
                row.get("routing-table", "main") != "main" or row.get("disabled", "false") != "false"):
                raise RuntimeError("Route ownership/topology mismatch")
            found[band] = row
        owned_ids = {row[".id"] for row in found.values()}
        if any(row.get(".id") not in owned_ids and
               row.get("dst-address") == self.config["remote_lan"] and
               row.get("routing-table", "main") == "main" and
               row.get("disabled", "false") != "true" for row in rows):
            raise RuntimeError("Unowned route competes for the remote LAN; operator review required")
        distances = [int(found[b]["distance"]) for b in ("5", "24")]
        if distances[0] == distances[1]:
            raise RuntimeError("Ambiguous equal-cost routes; operator review required")
        return found

    def preferred(self):
        """Configured preference may differ from the router's active forwarding route."""
        rows = self.routes()
        return min(rows, key=lambda band: int(rows[band]["distance"]))

    def active(self):
        active = [band for band, row in self.routes().items() if row.get("active") == "true"]
        return active[0] if len(active) == 1 else None

    def switch(self, target):
        rows = self.routes()
        old = "24" if target == "5" else "5"
        original = {b: rows[b]["distance"] for b in rows}
        try:
            # Stage at distance 2 while old=1, then demote old. Both radios stay on.
            for band, distance in ((target, "2"), (old, "20"), (target, "1")):
                self.request("ip/route/" + rows[band][".id"], {"distance": distance}, "PATCH")
            if self.active() != target:
                raise RuntimeError("Route readback failed")
        except Exception:
            for band in rows:
                try:
                    self.request("ip/route/" + rows[band][".id"], {"distance": original[band]}, "PATCH")
                except Exception:
                    LOG.critical("Route rollback failed; operator intervention required")
            raise


def validate(config):
    for flag in ("auto_apply", "hardware_acceptance_passed"):
        if type(config.get(flag, False)) is not bool:
            raise ValueError(f"{flag} must be a JSON boolean, not a quoted string")
    t = Thresholds(**config.get("thresholds", {}))
    if not (0 <= t.recover_loss <= t.max_loss <= 100 and 0 < t.recover_latency_ms <= t.max_latency_ms):
        raise ValueError("Invalid health thresholds")
    if not (0 < t.outage_seconds <= t.degrade_seconds < t.recovery_seconds and t.backup_ready_seconds >= 0 and t.max_gap_seconds > 0):
        raise ValueError("Invalid hysteresis thresholds")
    networks = []
    for band in ("5", "24"):
        b = config["bands"][band]
        net = ipaddress.ip_network(b["source"] + "/30", strict=False)
        if ipaddress.ip_address(b["peer"]) not in list(net.hosts()) or b["source"] == b["peer"]:
            raise ValueError("Each probe must target the opposite endpoint on its own /30")
        networks.append(net)
    if networks[0] == networks[1] or config["bands"]["5"]["interface"] == config["bands"]["24"]["interface"]:
        raise ValueError("Bands must use separate routed interfaces and subnets")
    if config.get("auto_apply") and not config.get("hardware_acceptance_passed"):
        raise ValueError("Automatic changes require completed hardware acceptance")
    if not 0.5 <= config.get("interval_seconds", 1) <= 5:
        raise ValueError("Probe interval must be 0.5..5 seconds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    validate(config)
    if "REPLACE_" in json.dumps(config):
        raise ValueError("Fill in reviewed interface names and peer MAC addresses first")
    dry_run = args.dry_run or not config.get("auto_apply", False)
    router = Router(config)
    policy = Policy(router.preferred(), Thresholds(**config.get("thresholds", {})))
    last_reason = None
    status_path = Path(config.get("status_file", "/run/irc-failover/status.json"))
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        while True:
            started = time.monotonic()
            # Probe each band every cycle, including standby after failback.
            jobs = {band: pool.submit(router.probe, band) for band in ("5", "24")}
            diag_job = pool.submit(router.diagnostics)
            samples = {band: job.result() for band, job in jobs.items()}
            diagnostics = diag_job.result()
            target, reason = policy.decide(samples["5"], samples["24"], time.monotonic())
            if target != policy.active:
                LOG.warning("%s %s -> %s: %s", "would switch" if dry_run else "switch", policy.active, target, reason)
                if not dry_run:
                    router.switch(target)  # Fail closed on errors; service does not blindly retry writes.
                policy.active = target
            elif reason != last_reason:
                LOG.info(reason)
            last_reason = reason
            record = {"updated_at": time.time(), "dry_run": dry_run, "selected_band": policy.active,
                      "reason": reason, "bands": {b: {**asdict(s), "usable": policy.usable(s), **diagnostics.get(b, {})} for b, s in samples.items()}}
            for band in record["bands"].values():
                if not math.isfinite(band["latency_ms"]): band["latency_ms"] = None
            temporary = status_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, allow_nan=False))
            temporary.replace(status_path)
            if args.once: break
            time.sleep(max(0, config.get("interval_seconds", 1) - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except Exception as exc:
        LOG.error("Controller stopped (%s). Check config, TLS, route ownership and local router availability.", type(exc).__name__)
        raise SystemExit(1)
