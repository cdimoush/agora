"""Tests for ErrorContext and on_error hook."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora.gateway import Agora
from agora.errors import ErrorContext
from agora.config import Config


BOT_USER_ID = 1000


def _history_messages(messages):
    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg
    return _history


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        channels={"general": "subscribe"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),
        typing_indicator=False,
        reply_threading=True,
        max_response_length=4000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_discord_msg(channel_name="general"):
    author = SimpleNamespace(id=2000, bot=False, display_name="User")
    channel = AsyncMock()
    channel.name = channel_name
    channel.id = 500
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=AsyncMock())
    channel.history = _history_messages([])

    msg = AsyncMock()
    msg.author = author
    msg.channel = channel
    msg.content = "hello"
    msg.id = 9999
    msg.mentions = []
    msg.reference = None
    msg.reply = AsyncMock()
    return msg


class TestOnError:
    @pytest.mark.asyncio
    async def test_on_message_error_calls_on_error(self):
        """When on_message raises, on_error is called with correct context."""
        errors_seen = []

        class ErrAgent(Agora):
            async def on_message(self, message):
                raise RuntimeError("boom")

            async def on_error(self, error, context):
                errors_seen.append((error, context))
                return None

        cfg = _make_config()
        bot = ErrAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {"general": "subscribe"}
        bot._channel_ids = {"general": 0}

        msg = _make_discord_msg()
        await bot._on_message(msg)

        assert len(errors_seen) == 1
        err, ctx = errors_seen[0]
        assert isinstance(err, RuntimeError)
        assert ctx.stage == "on_message"
        assert ctx.message is not None

    @pytest.mark.asyncio
    async def test_on_error_returning_string_sends_reply(self):
        """When on_error returns a string, it's sent as reply."""

        class FallbackAgent(Agora):
            async def on_message(self, message):
                raise RuntimeError("boom")

            async def on_error(self, error, context):
                return "sorry, something went wrong"

        cfg = _make_config()
        bot = FallbackAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {"general": "subscribe"}
        bot._channel_ids = {"general": 0}

        msg = _make_discord_msg()
        await bot._on_message(msg)
        msg.reply.assert_called_once()
        assert "sorry" in msg.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_error_raising_is_swallowed(self):
        """When on_error itself raises, it's silently swallowed."""

        class DoubleErrAgent(Agora):
            async def on_message(self, message):
                raise RuntimeError("first")

            async def on_error(self, error, context):
                raise RuntimeError("second")

        cfg = _make_config()
        bot = DoubleErrAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {"general": "subscribe"}
        bot._channel_ids = {"general": 0}

        msg = _make_discord_msg()
        # Should not raise
        await bot._on_message(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_error_returning_none_is_silent(self):
        """on_error returning None = no reply sent."""

        class SilentErrAgent(Agora):
            async def on_message(self, message):
                raise RuntimeError("boom")

            async def on_error(self, error, context):
                return None

        cfg = _make_config()
        bot = SilentErrAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {"general": "subscribe"}
        bot._channel_ids = {"general": 0}

        msg = _make_discord_msg()
        await bot._on_message(msg)
        msg.reply.assert_not_called()
        msg.channel.send.assert_not_called()


class TestErrorContext:
    def test_error_context_fields(self):
        ctx = ErrorContext(stage="on_message", message=None, channel="general")
        assert ctx.stage == "on_message"
        assert ctx.message is None
        assert ctx.channel == "general"

    def test_error_context_defaults(self):
        ctx = ErrorContext(stage="on_schedule")
        assert ctx.message is None
        assert ctx.channel is None
