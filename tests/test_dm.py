"""Tests for DM (Direct Message) support in gateway and message."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from agora.config import Config
from agora.gateway import Agora as AgoraBot
from agora.message import Message


# ── Helpers ───────────────────────────────────────────────────

BOT_USER_ID = 1000


def _history_messages(messages):
    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg
    return _history


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        channels={"dm": "subscribe", "bot-chat": "subscribe"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),
        typing_indicator=False,
        reply_threading=True,
        max_response_length=4000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_bot(config=None, **config_overrides) -> AgoraBot:
    cfg = config or _make_config(**config_overrides)
    bot = AgoraBot(cfg)
    mock_client = MagicMock()
    mock_client.user = SimpleNamespace(id=BOT_USER_ID)
    mock_client.guilds = []
    bot._client = mock_client
    bot._channel_map = {
        name: mode for name, mode in cfg.channels.items()
        if name != "dm"  # dm is not a guild channel
    }
    bot._channel_ids = {
        name: i for i, name in enumerate(cfg.channels)
        if name != "dm"
    }
    return bot


def _make_dm_message(*, author_id=2000, content="hello", mentions=None):
    """Create a mock Discord DM message."""
    author = SimpleNamespace(id=author_id, bot=False, display_name="Operator")
    channel = AsyncMock(spec=discord.DMChannel)
    channel.id = 9000
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=AsyncMock())
    channel.history = _history_messages([])
    msg = AsyncMock()
    msg.author = author
    msg.channel = channel
    msg.content = content
    msg.id = 8888
    msg.mentions = mentions or []
    msg.reply = AsyncMock()
    return msg


# ── Message.is_dm and channel_name ───────────────────────────


class TestMessageDM:
    def test_is_dm_true(self):
        dm_channel = MagicMock(spec=discord.DMChannel)
        dm_channel.id = 9000
        raw = SimpleNamespace(
            content="hi", author=SimpleNamespace(id=111, bot=False, display_name="Op"),
            channel=dm_channel, id=333, mentions=[],
        )
        msg = Message(raw, BOT_USER_ID)
        assert msg.is_dm is True
        assert msg.channel_name == "dm"

    def test_is_dm_false_for_guild(self):
        guild_channel = SimpleNamespace(name="general", id=500)
        raw = SimpleNamespace(
            content="hi", author=SimpleNamespace(id=111, bot=False, display_name="Op"),
            channel=guild_channel, id=333, mentions=[],
        )
        msg = Message(raw, BOT_USER_ID)
        assert msg.is_dm is False
        assert msg.channel_name == "general"


# ── Gateway DM routing ───────────────────────────────────────


class TestDMRouting:
    @pytest.mark.asyncio
    async def test_dm_dispatched_when_configured(self):
        """DM messages reach on_message when dm: subscribe is in config."""
        class DMAgent(AgoraBot):
            async def on_message(self, message):
                return "got it"

        bot = _make_bot(config=_make_config())
        bot.__class__ = DMAgent
        bot._use_legacy_api = False

        msg = _make_dm_message()
        await bot._on_message(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_dm_ignored_when_not_configured(self):
        """DM messages are dropped when dm is not in channels config."""
        bot = _make_bot(channels={"bot-chat": "subscribe"})
        msg = _make_dm_message()
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_caches_channel(self):
        """Gateway caches the DM channel on receipt for later proactive sends."""
        class DMAgent(AgoraBot):
            async def on_message(self, message):
                return "ok"

        bot = _make_bot()
        bot.__class__ = DMAgent
        bot._use_legacy_api = False

        assert bot._last_dm_channel is None
        msg = _make_dm_message()
        await bot._on_message(msg)
        assert bot._last_dm_channel is msg.channel

    @pytest.mark.asyncio
    async def test_dm_skips_exchange_cap(self):
        """Exchange cap is NOT checked for DMs."""
        class DMAgent(AgoraBot):
            async def on_message(self, message):
                return "reply"

        bot = _make_bot()
        bot.__class__ = DMAgent
        bot._use_legacy_api = False
        # Make cap checker always return True (would block non-DM)
        bot._exchange_cap.is_capped = AsyncMock(return_value=True)

        msg = _make_dm_message()
        await bot._on_message(msg)
        # Should still get a response despite cap being "reached"
        msg.reply.assert_called_once()
        # Cap checker should NOT have been called at all for DMs
        bot._exchange_cap.is_capped.assert_not_called()


# ── send() DM path ───────────────────────────────────────────


class TestDMSend:
    @pytest.mark.asyncio
    async def test_send_dm_uses_cached_channel(self):
        bot = _make_bot()
        dm_channel = AsyncMock(spec=discord.DMChannel)
        dm_channel.send = AsyncMock()
        bot._last_dm_channel = dm_channel

        await bot.send("dm", "hello operator")
        dm_channel.send.assert_called_once_with("hello operator")

    @pytest.mark.asyncio
    async def test_send_dm_skipped_when_no_cache(self):
        bot = _make_bot()
        assert bot._last_dm_channel is None
        # Should not raise, just skip
        await bot.send("dm", "hello")

    @pytest.mark.asyncio
    async def test_send_dm_truncates(self):
        bot = _make_bot(max_response_length=5)
        dm_channel = AsyncMock(spec=discord.DMChannel)
        dm_channel.send = AsyncMock()
        bot._last_dm_channel = dm_channel

        await bot.send("dm", "hello world")
        dm_channel.send.assert_called_once_with("hello")


# ── _get_channel_mode for DM ─────────────────────────────────


class TestGetChannelModeDM:
    def test_dm_returns_configured_mode(self):
        bot = _make_bot(channels={"dm": "subscribe", "bot-chat": "subscribe"})
        assert bot._get_channel_mode("dm") == "subscribe"

    def test_dm_returns_none_when_not_configured(self):
        bot = _make_bot(channels={"bot-chat": "subscribe"})
        assert bot._get_channel_mode("dm") is None

    def test_dm_mention_only_mode(self):
        bot = _make_bot(channels={"dm": "mention-only"})
        assert bot._get_channel_mode("dm") == "mention-only"


# ── _resolve_channels skips dm ────────────────────────────────


class TestResolveChannelsDM:
    def test_dm_not_warned_as_missing(self):
        """The dm key should not trigger 'not found on server' warning."""
        import io
        import logging

        bot = _make_bot(channels={"dm": "subscribe", "bot-chat": "subscribe"})
        guild = MagicMock()
        text_channel = MagicMock()
        text_channel.name = "bot-chat"
        text_channel.id = 100
        guild.text_channels = [text_channel]
        bot._client.guilds = [guild]

        handler = logging.StreamHandler(io.StringIO())
        handler.setLevel(logging.WARNING)
        agora_logger = logging.getLogger("agora")
        agora_logger.addHandler(handler)

        bot._resolve_channels()

        log_output = handler.stream.getvalue()
        assert "Channel 'dm'" not in log_output
        agora_logger.removeHandler(handler)
