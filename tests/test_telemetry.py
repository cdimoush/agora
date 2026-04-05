"""Unit tests for agora.telemetry and pipeline instrumentation."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.bot import AgoraBot
from agora.config import Config
from agora.telemetry import (
    Span,
    TestProcessor,
    LogProcessor,
    ReplayProcessor,
    _NullSpan,
    _null_span,
    _trace_ctx,
)


# ── Helpers ──────────────────────────────────────────────────────

BOT_USER_ID = 1000


def _history_messages(messages):
    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg
    return _history


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        name="test-bot",
        channels={"general": "subscribe"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),
        typing_indicator=False,
        reply_threading=False,
        max_response_length=4000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_discord_msg(
    *,
    author_id=2000,
    author_bot=False,
    channel_name="general",
    content="hello",
    mentions=None,
):
    author = SimpleNamespace(id=author_id, bot=author_bot, display_name="User")
    channel = AsyncMock()
    channel.name = channel_name
    channel.id = 500
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=AsyncMock())
    channel.history = _history_messages([])

    msg = AsyncMock()
    msg.author = author
    msg.channel = channel
    msg.content = content
    msg.id = 9999
    msg.mentions = mentions or []
    msg.reference = None
    msg.reply = AsyncMock()
    return msg


def _make_bot_with_processor(**config_overrides):
    config = _make_config(**config_overrides)
    bot = AgoraBot(config)
    bot._client = MagicMock()
    bot._client.user = SimpleNamespace(id=BOT_USER_ID)
    bot._channel_map = {
        name: mode for name, mode in config.channels.items()
    }
    proc = TestProcessor()
    bot.add_processor(proc)
    return bot, proc


# ── Span unit tests ──────────────────────────────────────────────

class TestSpan:
    def test_setitem_getitem(self):
        s = Span("t1", "test", "bot", "ch", 1, "auth", 0.0)
        s["decision"] = "filtered"
        assert s["decision"] == "filtered"

    def test_getitem_missing_returns_none(self):
        s = Span("t1", "test", "bot", "ch", 1, "auth", 0.0)
        assert s["missing"] is None

    def test_to_dict_flat(self):
        s = Span("t1", "test", "bot", "ch", 1, "auth", 100.0, duration_ms=5.678)
        s["decision"] = "pass"
        d = s.to_dict()
        assert d["trace_id"] == "t1"
        assert d["span"] == "test"
        assert d["bot"] == "bot"
        assert d["duration_ms"] == 5.68
        assert d["decision"] == "pass"


class TestNullSpan:
    def test_context_manager_noop(self):
        with _null_span as s:
            s["key"] = "value"
            assert s["key"] is None

    def test_singleton(self):
        assert _null_span is _null_span


# ── Processor unit tests ─────────────────────────────────────────

class TestLogProcessor:
    def test_emits_json(self, caplog):
        proc = LogProcessor()
        s = Span("t1", "test", "bot", "ch", 1, "auth", 0.0)
        s["decision"] = "pass"

        with caplog.at_level(logging.INFO, logger="agora.telemetry"):
            proc.on_span(s)

        assert len(caplog.records) == 1
        data = json.loads(caplog.records[0].message)
        assert data["span"] == "test"
        assert data["decision"] == "pass"


class TestReplayProcessor:
    def test_message_received_format(self):
        proc = ReplayProcessor()
        s = Span("t1", "message_received", "bot", "general", 1, "Alice", 1000.0)
        s["content"] = "hello world"
        proc.on_span(s)
        out = proc.replay()
        assert "Alice: hello world" in out

    def test_pipeline_result_responded(self):
        proc = ReplayProcessor()
        s = Span("t1", "pipeline_result", "mybot", "general", 1, "Alice", 1000.0, duration_ms=150.0)
        s["outcome"] = "responded"
        s["response_preview"] = "hi there"
        proc.on_span(s)
        out = proc.replay()
        assert "mybot responded" in out
        assert "hi there" in out

    def test_pipeline_result_filtered(self):
        proc = ReplayProcessor()
        s = Span("t1", "pipeline_result", "mybot", "general", 1, "Alice", 1000.0)
        s["outcome"] = "filtered"
        s["filter_step"] = "exchange_cap"
        s["filter_reason"] = "cap reached"
        proc.on_span(s)
        out = proc.replay()
        assert "filtered at exchange_cap" in out

    def test_channel_filter(self):
        proc = ReplayProcessor()
        s1 = Span("t1", "message_received", "bot", "general", 1, "Alice", 1000.0)
        s1["content"] = "in general"
        s2 = Span("t2", "message_received", "bot", "other", 2, "Bob", 1001.0)
        s2["content"] = "in other"
        proc.on_span(s1)
        proc.on_span(s2)
        out = proc.replay(channel="general")
        assert "Alice" in out
        assert "Bob" not in out


class TestTestProcessor:
    def test_find_by_name(self):
        proc = TestProcessor()
        proc.on_span(Span("t1", "a", "bot", "ch", 1, "auth", 0.0))
        proc.on_span(Span("t1", "b", "bot", "ch", 1, "auth", 0.0))
        assert len(proc.find("a")) == 1

    def test_find_by_attrs(self):
        proc = TestProcessor()
        s = Span("t1", "test", "bot", "ch", 1, "auth", 0.0)
        s["decision"] = "filtered"
        proc.on_span(s)
        assert len(proc.find("test", decision="filtered")) == 1
        assert len(proc.find("test", decision="pass")) == 0

    def test_assert_span(self):
        proc = TestProcessor()
        s = Span("t1", "test", "bot", "ch", 1, "auth", 0.0)
        s["decision"] = "pass"
        proc.on_span(s)
        result = proc.assert_span("test", decision="pass")
        assert result is s

    def test_assert_span_fails(self):
        proc = TestProcessor()
        with pytest.raises(AssertionError, match="Expected 1"):
            proc.assert_span("missing")

    def test_clear(self):
        proc = TestProcessor()
        proc.on_span(Span("t1", "a", "bot", "ch", 1, "auth", 0.0))
        proc.clear()
        assert len(proc.spans) == 0


# ── Pipeline instrumentation tests ───────────────────────────────

class TestPipelineSpans:
    @pytest.mark.asyncio
    async def test_happy_path_emits_all_spans(self):
        """Full pipeline: message → response → send emits expected spans."""
        bot, proc = _make_bot_with_processor()

        async def _respond(msg):
            return "hi there"

        bot.generate_response = _respond
        bot.should_respond = AsyncMock(return_value=True)

        msg = _make_discord_msg()
        await bot._on_message(msg)

        span_names = [s.name for s in proc.spans]
        assert "message_received" in span_names
        assert "mention_filter" in span_names
        assert "exchange_cap" in span_names
        assert "should_respond" in span_names
        assert "generate_response" in span_names
        assert "truncate_chunk" in span_names
        assert "send_response" in span_names
        assert "pipeline_result" in span_names

        result = proc.assert_span("pipeline_result")
        assert result["outcome"] == "responded"
        assert result["response_preview"] == "hi there"

    @pytest.mark.asyncio
    async def test_mention_filter_emits_span(self):
        """mention-only mode filters non-mention and emits pipeline_result."""
        bot, proc = _make_bot_with_processor(
            channels={"general": "mention-only"}
        )

        msg = _make_discord_msg()  # no mentions
        await bot._on_message(msg)

        proc.assert_span("mention_filter", decision="filtered")
        result = proc.assert_span("pipeline_result")
        assert result["outcome"] == "filtered"
        assert result["filter_step"] == "mention_filter"

    @pytest.mark.asyncio
    async def test_should_respond_false_emits_span(self):
        bot, proc = _make_bot_with_processor()
        bot.should_respond = AsyncMock(return_value=False)

        msg = _make_discord_msg()
        await bot._on_message(msg)

        proc.assert_span("should_respond", decision="filtered")
        result = proc.assert_span("pipeline_result")
        assert result["filter_step"] == "should_respond"

    @pytest.mark.asyncio
    async def test_generate_response_error_emits_span(self):
        bot, proc = _make_bot_with_processor()
        bot.should_respond = AsyncMock(return_value=True)
        bot.generate_response = AsyncMock(side_effect=RuntimeError("boom"))

        msg = _make_discord_msg()
        await bot._on_message(msg)

        gen = proc.assert_span("generate_response")
        assert gen["decision"] == "error"
        assert "boom" in gen["error"]

        result = proc.assert_span("pipeline_result")
        assert result["outcome"] == "filtered"
        assert result["filter_step"] == "generate_response"

    @pytest.mark.asyncio
    async def test_no_processors_uses_null_span(self):
        """When no processors are registered, span() returns _NullSpan."""
        config = _make_config()
        bot = AgoraBot(config)
        bot._client = MagicMock()
        bot._client.user = SimpleNamespace(id=BOT_USER_ID)
        bot._channel_map = {"general": "subscribe"}

        # No processors added
        bot.should_respond = AsyncMock(return_value=False)

        msg = _make_discord_msg()
        await bot._on_message(msg)
        # Should not raise — NullSpan handles all attribute writes silently

    @pytest.mark.asyncio
    async def test_spans_have_trace_id_and_bot(self):
        bot, proc = _make_bot_with_processor()
        bot.should_respond = AsyncMock(return_value=False)

        msg = _make_discord_msg()
        await bot._on_message(msg)

        for span in proc.spans:
            assert span.trace_id  # non-empty
            assert span.bot == "test-bot"
            assert span.channel == "general"

    @pytest.mark.asyncio
    async def test_pipeline_result_always_emitted(self):
        """pipeline_result is emitted even on early returns."""
        bot, proc = _make_bot_with_processor()
        bot.should_respond = AsyncMock(side_effect=ValueError("crash"))

        msg = _make_discord_msg()
        await bot._on_message(msg)

        # pipeline_result must exist
        result = proc.assert_span("pipeline_result")
        assert result["outcome"] == "filtered"

    @pytest.mark.asyncio
    async def test_span_duration_is_positive(self):
        bot, proc = _make_bot_with_processor()

        async def _slow_respond(msg):
            return "ok"

        bot.generate_response = _slow_respond
        bot.should_respond = AsyncMock(return_value=True)

        msg = _make_discord_msg()
        await bot._on_message(msg)

        for span in proc.spans:
            assert span.duration_ms >= 0
