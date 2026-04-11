"""Universal event capture for Agora agents.

Every observable action (message, inference, lifecycle) emits an Event
with a fixed envelope and typed payload. EventCollector manages sessions,
sequencing, processor fan-out, and optional JSONL persistence.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


logger = logging.getLogger("agora.events")


# ── Event ────────────────────────────────────────────────────────

@dataclass
class Event:
    """A single observable action by an agent."""

    agent: str
    event_type: str
    trace_id: str
    session_id: str
    ts: float
    seq: int
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Flat dict for JSON serialization (envelope + payload merged)."""
        d = {
            "agent": self.agent,
            "type": self.event_type,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "ts": self.ts,
            "seq": self.seq,
        }
        d.update(self.payload)
        return d


# ── Processor protocol ───────────────────────────────────────────

@runtime_checkable
class EventProcessor(Protocol):
    def on_event(self, event: Event) -> None: ...


# ── EventCollector ───────────────────────────────────────────────

class EventCollector:
    """Single entry point for all event capture.

    Fans out to registered EventProcessors and optionally persists
    to an append-only JSONL file at ``data_dir/events.jsonl``.
    """

    def __init__(self, agent_name: str, data_dir: Path | None = None):
        self._agent = agent_name
        self._data_dir = data_dir
        self._seq = 0
        self._session_id: str | None = None
        self._trace_id: str | None = None
        self._processors: list[EventProcessor] = []

    # ── Session lifecycle (called by library, not operators) ─────

    def start_session(self, session_id: str | None = None) -> str:
        """Begin a new logical conversation session."""
        self._session_id = session_id or uuid.uuid4().hex[:12]
        return self._session_id

    def end_session(self) -> None:
        """End the current session."""
        self._session_id = None

    # ── Emit ─────────────────────────────────────────────────────

    def emit(self, event_type: str, **payload) -> Event:
        """Emit an event. Fans out to processors, then persists (best-effort)."""
        self._seq += 1
        event = Event(
            agent=self._agent,
            event_type=event_type,
            trace_id=self._trace_id or "none",
            session_id=self._session_id or "none",
            ts=time.time(),
            seq=self._seq,
            payload=payload,
        )
        # In-memory fan-out first (always)
        for p in self._processors:
            try:
                p.on_event(event)
            except Exception:
                pass  # never crash for telemetry
        # Persist (best-effort)
        if self._data_dir is not None:
            self._write(event)
        return event

    def add_processor(self, processor: EventProcessor) -> None:
        """Register an event processor for real-time consumption."""
        self._processors.append(processor)

    # ── Persistence ──────────────────────────────────────────────

    def _write(self, event: Event) -> None:
        """Append one JSON line. Open-write-close per event."""
        try:
            events_dir = self._data_dir / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
            path = events_dir / "events.jsonl"
            with open(path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except OSError as e:
            logger.warning("Event write failed: %s", e)
