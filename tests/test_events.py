"""Tests for the event capture system (agora/events.py + gateway integration)."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.events import Event, EventCollector, EventProcessor


# ── Event dataclass ──────────────────────────────────────────────


class TestEvent:
    def test_to_dict_flat(self):
        e = Event(
            agent="dev",
            event_type="message.received",
            trace_id="abc123",
            session_id="s-001",
            ts=1000.0,
            seq=1,
            payload={"author": "alice", "content": "hello"},
        )
        d = e.to_dict()
        assert d["agent"] == "dev"
        assert d["type"] == "message.received"
        assert d["trace_id"] == "abc123"
        assert d["session_id"] == "s-001"
        assert d["ts"] == 1000.0
        assert d["seq"] == 1
        # Payload fields merged into top level
        assert d["author"] == "alice"
        assert d["content"] == "hello"
        # No nested 'payload' key
        assert "payload" not in d

    def test_to_dict_empty_payload(self):
        e = Event(
            agent="nova", event_type="lifecycle.start",
            trace_id="none", session_id="none",
            ts=0.0, seq=0,
        )
        d = e.to_dict()
        assert d["agent"] == "nova"
        assert d["type"] == "lifecycle.start"

    def test_to_dict_is_json_serializable(self):
        e = Event(
            agent="dev", event_type="inference.response",
            trace_id="t1", session_id="s1",
            ts=time.time(), seq=42,
            payload={"response": "some text", "cost_usd": 0.003},
        )
        line = json.dumps(e.to_dict())
        parsed = json.loads(line)
        assert parsed["response"] == "some text"


# ── EventCollector ───────────────────────────────────────────────


class TestEventCollector:
    def test_emit_no_data_dir(self):
        """With data_dir=None, emit works but writes nothing."""
        c = EventCollector("test-agent", data_dir=None)
        event = c.emit("test.event", key="value")
        assert event.agent == "test-agent"
        assert event.event_type == "test.event"
        assert event.payload == {"key": "value"}

    def test_seq_monotonic(self):
        c = EventCollector("test-agent")
        e1 = c.emit("a")
        e2 = c.emit("b")
        e3 = c.emit("c")
        assert e1.seq == 1
        assert e2.seq == 2
        assert e3.seq == 3

    def test_session_lifecycle(self):
        c = EventCollector("test-agent")
        sid = c.start_session()
        assert sid is not None
        assert len(sid) == 12

        e = c.emit("test")
        assert e.session_id == sid

        c.end_session()
        e2 = c.emit("test2")
        assert e2.session_id == "none"

    def test_session_custom_id(self):
        c = EventCollector("test-agent")
        sid = c.start_session("my-session")
        assert sid == "my-session"
        e = c.emit("test")
        assert e.session_id == "my-session"

    def test_trace_id_propagation(self):
        c = EventCollector("test-agent")
        c._trace_id = "trace-abc"
        e = c.emit("test")
        assert e.trace_id == "trace-abc"

        c._trace_id = None
        e2 = c.emit("test2")
        assert e2.trace_id == "none"

    def test_emit_writes_jsonl(self, tmp_path):
        c = EventCollector("test-agent", data_dir=tmp_path)
        c.emit("first.event", data="hello")
        c.emit("second.event", data="world")

        jsonl_path = tmp_path / "events" / "events.jsonl"
        assert jsonl_path.exists()

        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["type"] == "first.event"
        assert first["data"] == "hello"
        assert first["seq"] == 1

        second = json.loads(lines[1])
        assert second["type"] == "second.event"
        assert second["seq"] == 2

    def test_emit_creates_directory(self, tmp_path):
        data_dir = tmp_path / "nested" / "data"
        c = EventCollector("test-agent", data_dir=data_dir)
        c.emit("test")
        assert (data_dir / "events" / "events.jsonl").exists()

    def test_write_failure_logs_warning(self, tmp_path):
        """Write failure should log warning, not crash."""
        # Use a path that can't be written to
        bad_path = Path("/nonexistent/readonly/path")
        c = EventCollector("test-agent", data_dir=bad_path)

        # Should not raise
        event = c.emit("test.event", key="value")
        assert event is not None  # Event still created
        assert event.seq == 1

    def test_processor_fanout(self):
        events_received = []

        class Collector:
            def on_event(self, event):
                events_received.append(event)

        c = EventCollector("test-agent")
        c.add_processor(Collector())

        c.emit("test.a", x=1)
        c.emit("test.b", x=2)

        assert len(events_received) == 2
        assert events_received[0].event_type == "test.a"
        assert events_received[1].event_type == "test.b"

    def test_processor_exception_swallowed(self):
        class BadProcessor:
            def on_event(self, event):
                raise RuntimeError("boom")

        c = EventCollector("test-agent")
        c.add_processor(BadProcessor())

        # Should not raise
        event = c.emit("test")
        assert event.seq == 1

    def test_processor_receives_before_disk_write(self, tmp_path):
        """Processors should receive events even if disk write fails."""
        events_received = []

        class Collector:
            def on_event(self, event):
                events_received.append(event)

        bad_path = Path("/nonexistent/path")
        c = EventCollector("test-agent", data_dir=bad_path)
        c.add_processor(Collector())

        c.emit("test")
        assert len(events_received) == 1


# ── Gateway integration (span bridge) ───────────────────────────


class TestSpanBridge:
    """Test that span completion emits pipeline.step events."""

    def _make_bot(self, tmp_path=None):
        """Create an Agora instance with event capture."""
        from agora.config import Config

        config = Config(
            token_env="TEST_TOKEN",
            name="test-bot",
            data_dir=str(tmp_path) if tmp_path else None,
        )

        with patch.dict("os.environ", {"TEST_TOKEN": "fake-token"}):
            from agora.gateway import Agora
            bot = Agora(config)

        return bot

    def test_emit_available_on_bot(self):
        bot = self._make_bot()
        event = bot.emit("custom.event", key="value")
        assert event.agent == "test-bot"
        assert event.event_type == "custom.event"
        assert event.payload == {"key": "value"}

    def test_span_emits_pipeline_step(self, tmp_path):
        bot = self._make_bot(tmp_path)

        # Set up trace context (normally done by _start_trace)
        from agora.telemetry import _trace_ctx
        _trace_ctx.set({
            "trace_id": "test-trace",
            "bot": "test-bot",
            "channel": "test-channel",
            "message_id": 12345,
            "author": "tester",
        })
        bot._collector._trace_id = "test-trace"
        bot._collector.start_session("test-session")

        with bot.span("test_step", custom_attr="hello") as s:
            s["decision"] = "pass"

        # Check events.jsonl
        jsonl_path = tmp_path / "events" / "events.jsonl"
        assert jsonl_path.exists()

        lines = jsonl_path.read_text().strip().split("\n")
        # Should have at least one pipeline.step event
        step_events = [
            json.loads(l) for l in lines
            if json.loads(l)["type"] == "pipeline.step"
        ]
        assert len(step_events) == 1
        ev = step_events[0]
        assert ev["step"] == "test_step"
        assert ev["decision"] == "pass"
        assert ev["custom_attr"] == "hello"
        assert ev["trace_id"] == "test-trace"
        assert ev["session_id"] == "test-session"
        assert "duration_ms" in ev

        # Clean up context
        _trace_ctx.set(None)

    def test_span_nullspan_when_no_sinks(self):
        """With no processors and no data_dir, span returns NullSpan."""
        bot = self._make_bot()  # no data_dir
        from agora.telemetry import _NullSpan

        with bot.span("test") as s:
            assert isinstance(s, _NullSpan)

    def test_add_event_processor(self, tmp_path):
        bot = self._make_bot()
        events = []

        class MyProcessor:
            def on_event(self, event):
                events.append(event)

        bot.add_event_processor(MyProcessor())
        bot.emit("custom.test", value=42)

        assert len(events) == 1
        assert events[0].payload["value"] == 42
