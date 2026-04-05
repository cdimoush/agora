"""Tests for get_history(), get_channels(), and connection guard."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora.gateway import Agora
from agora.config import Config
from agora.message import Message


BOT_USER_ID = 1000


def _history_messages(messages):
    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg
    return _history


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        channels={"general": "subscribe", "announce": "write-only"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),
        typing_indicator=False,
        reply_threading=True,
        max_response_length=4000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_discord_history_msg(content="hi", author_name="User", bot=False):
    author = SimpleNamespace(id=2000, bot=bot, display_name=author_name)
    channel = SimpleNamespace(name="general", id=500)
    msg = SimpleNamespace(
        author=author, channel=channel, content=content,
        id=9999, mentions=[], reference=None,
    )
    return msg


def _make_bot(connected=True, **config_overrides) -> Agora:
    cfg = _make_config(**config_overrides)
    bot = Agora(cfg)
    mock_client = MagicMock()
    mock_client.user = SimpleNamespace(id=BOT_USER_ID) if connected else None
    mock_client.guilds = []
    bot._client = mock_client
    bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
    bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

    # Mock get_channel
    channels = {}
    for name, idx in bot._channel_ids.items():
        ch = AsyncMock()
        ch.name = name
        ch.id = idx
        ch.send = AsyncMock()
        ch.history = _history_messages([])
        channels[idx] = ch
    mock_client.get_channel = lambda cid: channels.get(cid)
    return bot


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_returns_list_of_messages(self):
        bot = _make_bot()
        raw_msgs = [_make_discord_history_msg("msg1"), _make_discord_history_msg("msg2")]
        ch = bot._client.get_channel(bot._channel_ids["general"])
        ch.history = _history_messages(raw_msgs)

        result = await bot.get_history("general", limit=10)
        assert len(result) == 2
        assert all(isinstance(m, Message) for m in result)
        assert result[0].content == "msg1"

    @pytest.mark.asyncio
    async def test_unknown_channel_raises(self):
        bot = _make_bot()
        with pytest.raises(ValueError, match="not in config"):
            await bot.get_history("random")

    @pytest.mark.asyncio
    async def test_before_connection_raises(self):
        bot = _make_bot(connected=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            await bot.get_history("general")


class TestGetChannels:
    def test_returns_configured_channels(self):
        bot = _make_bot()
        channels = bot.get_channels()
        assert channels == {"general": "subscribe", "announce": "write-only"}

    def test_returns_copy(self):
        bot = _make_bot()
        channels = bot.get_channels()
        channels["new"] = "subscribe"
        assert "new" not in bot.get_channels()

    def test_before_connection_raises(self):
        bot = _make_bot(connected=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            bot.get_channels()


class TestConnectionGuard:
    @pytest.mark.asyncio
    async def test_send_before_connection_raises(self):
        bot = _make_bot(connected=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            await bot.send("general", "hello")

    @pytest.mark.asyncio
    async def test_reply_before_connection_raises(self):
        bot = _make_bot(connected=False)
        discord_msg = MagicMock()
        discord_msg.channel = MagicMock()
        discord_msg.channel.name = "general"
        discord_msg.channel.id = 0
        discord_msg.author = SimpleNamespace(id=2000, bot=False, display_name="User")
        discord_msg.mentions = []
        discord_msg.reference = None
        discord_msg.content = "hi"
        discord_msg.id = 9999
        msg = Message(discord_msg, BOT_USER_ID)
        with pytest.raises(RuntimeError, match="Not connected"):
            await bot.reply(msg, "hello")
