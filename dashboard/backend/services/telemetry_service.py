
"""
services/telemetry_service.py
------------------------------
Stores the latest rover telemetry and additional external data,
including MikroTik radio-link statistics.
"""

from __future__ import annotations
from copy import deepcopy
import asyncio
import time
from typing import Any, Optional

from models.telemetry import TelemetrySnapshot


class TelemetryService:
    """Async-safe store for the latest telemetry snapshot."""

    def __init__(self) -> None:
        self._snapshot: Optional[TelemetrySnapshot] = None

        # Stores external telemetry independently of rover packets.
        self._custom_data: dict[str, Any] = {}

        self._update_event: asyncio.Event = asyncio.Event()
        self._start_time: float = time.monotonic()
        self._update_count: int = 0

    # ---------------------------------------------------------
    # Rover telemetry update
    # ---------------------------------------------------------

    def update_telemetry(self, snapshot: TelemetrySnapshot) -> None:
        """Stores rover telemetry while preserving external data."""

        if self._custom_data:
            merged_custom = {
                **snapshot.custom,
                **self._custom_data,
            }

            snapshot = snapshot.model_copy(
                update={"custom": merged_custom}
            )

        self._snapshot = snapshot
        self._update_count += 1
        self._update_event.set()

    # ---------------------------------------------------------
    # External telemetry update (MikroTik)
    # ---------------------------------------------------------

    def update_custom(self, custom: dict[str, Any]) -> None:
        """Updates external telemetry without modifying rover sensors."""

        self._custom_data.update(custom)

        # Wait until the first rover snapshot exists.
        if self._snapshot is None:
            return

        merged_custom = {
            **self._snapshot.custom,
            **self._custom_data,
        }

        self._snapshot = self._snapshot.model_copy(
            update={"custom": merged_custom}
        )

        self._update_count += 1
        self._update_event.set()

    # ---------------------------------------------------------
    # Read path
    # ---------------------------------------------------------

    def get_telemetry(self) -> Optional[TelemetrySnapshot]:
        """Returns the latest snapshot, or None if none received yet."""
        return self._snapshot
    def get_custom_data(self) -> dict[str, Any]:
        """
        Returns external telemetry independently of rover telemetry.
        Used by the independent Radio Link API endpoint.
        """
        return deepcopy(self._custom_data)
    # ---------------------------------------------------------
    # Broadcast helper
    # ---------------------------------------------------------

    async def wait_for_update(self) -> TelemetrySnapshot:
        """Waits until fresh telemetry arrives."""

        await self._update_event.wait()
        self._update_event.clear()

        return self._snapshot  # type: ignore[return-value]
def get_custom_data(self) -> dict[str, Any]:
     """Returns external telemetry independently of rover telemetry."""

     return deepcopy(self._custom_data)
    # ---------------------------------------------------------
    # Diagnostics
    # ---------------------------------------------------------

@property
def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

@property
def update_count(self) -> int:
        return self._update_count


# Module-level singleton shared across the backend.
telemetry_service = TelemetryService()
