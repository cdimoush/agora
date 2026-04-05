"""Lightweight telemetry for the Agora dispatch pipeline.

Each _on_message invocation creates a trace; each pipeline step emits a Span.
Processors consume spans for logging, replay, and test assertions.
Zero overhead when no processors are registered (_NullSpan path).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


# ── Trace context (async-safe, one per _on_message call) ─────────

_trace_ctx: ContextVar[dict | None] = ContextVar("agora_trace", default=None)


# ── Span ─────────────────────────────────────────────────────────

@dataclass
class Span:
    """A timed operation within a message dispatch trace."""

    trace_id: str
    name: str
    bot: str
    channel: str
    message_id: int
    author: str
    timestamp: float          # time.time() wall clock
    duration_ms: float = 0.0  # filled on context-manager exit
    _attrs: dict = field(default_factory=dict, repr=False)

    def __setitem__(self, key: str, value) -> None:
        self._attrs[key] = value

    def __getitem__(self, key: str):
        return self._attrs.get(key)

    def to_dict(self) -> dict:
        """Flat dict for JSON serialization."""
        d = {
            "trace_id": self.trace_id,
            "span": self.name,
            "bot": self.bot,
            "channel": self.channel,
            "message_id": self.message_id,
            "author": self.author,
            "ts": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
        }
        d.update(self._attrs)
        return d


class _NullSpan:
    """No-op span returned when no processors are registered."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def __setitem__(self, k, v):
        pass

    def __getitem__(self, k):
        return None


_null_span = _NullSpan()  # singleton


# ── Processor protocol ───────────────────────────────────────────

@runtime_checkable
class TelemetryProcessor(Protocol):
    def on_span(self, span: Span) -> None: ...


# ── Built-in processors ─────────────────────────────────────────

class LogProcessor:
    """Emit each span as a single-line JSON string via Python logging."""

    def __init__(self, logger_name: str = "agora.telemetry"):
        self._logger = logging.getLogger(logger_name)

    def on_span(self, span: Span) -> None:
        self._logger.info(json.dumps(span.to_dict()))


class ReplayProcessor:
    """Collect spans and format a human-readable conversation replay."""

    def __init__(self):
        self.spans: list[Span] = []

    def on_span(self, span: Span) -> None:
        self.spans.append(span)

    def replay(self, channel: str | None = None) -> str:
        """Format collected spans as a conversation timeline."""
        filtered = self.spans
        if channel:
            filtered = [s for s in filtered if s.channel == channel]
        filtered.sort(key=lambda s: s.timestamp)

        lines: list[str] = []
        for s in filtered:
            ts = datetime.fromtimestamp(s.timestamp, tz=timezone.utc).strftime("%H:%M:%S")
            ch = f"#{s.channel}"

            if s.name == "message_received":
                content = s["content"] or ""
                lines.append(f"[{ts}] {ch}  {s.author}: {content}")
            elif s.name == "pipeline_result":
                outcome = s["outcome"]
                if outcome == "responded":
                    preview = s["response_preview"] or ""
                    lines.append(
                        f"[{ts}] {ch}  <- {s.bot} responded "
                        f"({s.duration_ms:.1f}ms): {preview!r}"
                    )
                elif outcome == "filtered":
                    step = s["filter_step"] or "unknown"
                    reason = s["filter_reason"] or ""
                    lines.append(
                        f"[{ts}] {ch}  -- {s.bot} filtered at {step}: {reason}"
                    )
            elif s.name in ("mention_filter", "exchange_cap", "should_respond"):
                decision = s["decision"]
                if decision and decision != "pass":
                    reason = s["reason"] or ""
                    lines.append(
                        f"[{ts}] {ch}  -> {s.bot}: {s.name} {decision}"
                        + (f" ({reason})" if reason else "")
                    )
            elif s.name == "generate_response":
                if s["decision"] == "pass":
                    lines.append(
                        f"[{ts}] {ch}  -> {s.bot}: generate_response "
                        f"({s.duration_ms:.0f}ms)"
                    )

        return "\n".join(lines)


class TestProcessor:
    """Collect spans in memory for test assertions."""

    def __init__(self):
        self.spans: list[Span] = []

    def on_span(self, span: Span) -> None:
        self.spans.append(span)

    def find(self, name: str | None = None, **attrs) -> list[Span]:
        """Find spans matching criteria."""
        results = self.spans
        if name:
            results = [s for s in results if s.name == name]
        for k, v in attrs.items():
            results = [s for s in results if s[k] == v]
        return results

    def assert_span(self, name: str, **attrs) -> Span:
        """Assert exactly one span matches. Return it."""
        matches = self.find(name, **attrs)
        assert len(matches) == 1, (
            f"Expected 1 '{name}' span matching {attrs}, found {len(matches)}"
        )
        return matches[0]

    def clear(self) -> None:
        self.spans.clear()
