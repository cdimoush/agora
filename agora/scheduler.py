"""Scheduler — interval parsing and asyncio timer for on_schedule dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Awaitable

logger = logging.getLogger("agora")

_INTERVAL_RE = re.compile(r"^(\d+)(s|m|h)$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_interval(s: str) -> float:
    """Parse an interval string like '1h', '30m', '5s' into seconds.

    Raises ValueError on invalid format.
    """
    match = _INTERVAL_RE.match(s.strip())
    if not match:
        raise ValueError(
            f"Invalid interval '{s}'. Use format like '1h', '30m', '5s'."
        )
    value = int(match.group(1))
    unit = match.group(2)
    return float(value * _UNIT_SECONDS[unit])


class SchedulerTask:
    """Runs a callback at a fixed interval using asyncio."""

    def __init__(self, interval_seconds: float, callback: Callable[[], Awaitable[None]]):
        self._interval = interval_seconds
        self._callback = callback
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the scheduler loop."""
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._callback()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # errors handled by caller's on_error

    def cancel(self) -> None:
        """Cancel the scheduler."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
