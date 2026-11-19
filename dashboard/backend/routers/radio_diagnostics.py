"""Operator endpoint for an explicitly requested MikroTik noise-floor scan.

The scan is disruptive: it disconnects Wi-Fi clients on the selected interface.
It is disabled unless both a server-side safety flag and an operator token are set.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ingestion.mikrotik_collector import (
    load_env_file,
    request_noise_floor_scan,
)

router = APIRouter(tags=["Radio Diagnostics"])


class NoiseFloorScanRequest(BaseModel):
    router: Literal["mantbox", "netmetal"]
    frequencies_mhz: list[int] = Field(default_factory=lambda: [5180, 5200, 5220, 5240])
    acknowledge_disruption: bool = False


@router.post("/api/radio-link/noise-floor-scan")
async def trigger_noise_floor_scan(
    request: NoiseFloorScanRequest,
    x_operator_token: str | None = Header(default=None, alias="X-Operator-Token"),
):
    """Run a one-shot scan after explicit operator acknowledgement."""
    load_env_file()

    expected_token = os.getenv("MIKROTIK_NOISE_SCAN_API_TOKEN", "")
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Noise-scan endpoint is not configured. Set MIKROTIK_NOISE_SCAN_API_TOKEN in backend/.env and restart the backend.",
        )
    if not x_operator_token or not hmac.compare_digest(x_operator_token, expected_token):
        raise HTTPException(status_code=401, detail="Operator token is missing or incorrect.")
    if not request.acknowledge_disruption:
        raise HTTPException(status_code=400, detail="Explicit disruption acknowledgement is required.")
    if not request.frequencies_mhz:
        raise HTTPException(status_code=400, detail="At least one scan frequency is required.")

    try:
        snapshot = await request_noise_floor_scan(
            request.router,
            frequencies_mhz=request.frequencies_mhz,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        code = 503 if "collector is not running" in message.lower() else 409
        raise HTTPException(status_code=code, detail=message) from exc
    except Exception as exc:
        # Do not return router credentials or internal client details to the browser.
        raise HTTPException(
            status_code=502,
            detail=f"RouterOS noise-floor scan failed: {type(exc).__name__}. Check backend logs.",
        ) from exc

    return {"success": True, "snapshot": snapshot}
