"""Tests for Agora.send() and Agora.reply() with cap enforcement."""

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


def _make_history_msg(*, bot=False):
    author = SimpleNamespace(bot=bot, display_name="Bot" if bot else "Human")
    return SimpleNamespace(author=author)


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


def _make_bot(config=None, **config_overrides) -> Agora:
    cfg = config or _make_config(**config_overrides)
    bot = Agora(cfg)
    mock_client = MagicMock()
    mock_client.user = SimpleNamespace(id=BOT_USER_ID)
    mock_client.guilds = []
    bot._client = mock_client
    bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
    bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

    # Mock get_channel to return AsyncMock channels
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


class TestSend:
    @pytest.mark.asyncio
    async def test_send_to_valid_channel(self):
        bot = _make_bot()
        await bot.send("general", "hello")
        ch = bot._client.get_channel(bot._channel_ids["general"])
        ch.send.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_to_unknown_channel_raises(self):
        bot = _make_bot()
        with pytest.raises(ValueError, match="not in config"):
            await bot.send("random", "hello")

    @pytest.mark.asyncio
    async def test_send_to_write_only_skips_cap(self):
        bot = _make_bot()
        # Fill history with bot messages to hit cap
        ch = bot._client.get_channel(bot._channel_ids["announce"])
        ch.history = _history_messages([_make_history_msg(bot=True) for _ in range(10)])
        await bot.send("announce", "update")
        ch.send.assert_called_once_with("update")

    @pytest.mark.asyncio
    async def test_send_respects_exchange_cap(self):
        bot = _make_bot(exchange_cap=3)
        ch = bot._client.get_channel(bot._channel_ids["general"])
        ch.history = _history_messages([_make_history_msg(bot=True) for _ in range(3)])
        await bot.send("general", "should not send")
        ch.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_truncates_long_content(self):
        bot = _make_bot(max_response_length=10)
        await bot.send("general", "a" * 100)
        ch = bot._client.get_channel(bot._channel_ids["general"])
        sent_text = ch.send.call_args[0][0]
        assert len(sent_text) <= 10


class TestReply:
    @pytest.mark.asyncio
    async def test_reply_threads(self):
        bot = _make_bot()
        discord_msg = AsyncMock()
        discord_msg.channel = bot._client.get_channel(bot._channel_ids["general"])
        discord_msg.channel.name = "general"
        discord_msg.channel.id = bot._channel_ids["general"]
        discord_msg.author = SimpleNamespace(id=2000, bot=False, display_name="User")
        discord_msg.mentions = []
        discord_msg.reference = None
        discord_msg.content = "hello"
        discord_msg.id = 9999
        discord_msg.reply = AsyncMock()

        message = Message(discord_msg, BOT_USER_ID)
        await bot.reply(message, "hey back")
        discord_msg.reply.assert_called_once_with("hey back", mention_author=False)

    @pytest.mark.asyncio
    async def test_reply_respects_cap(self):
        bot = _make_bot(exchange_cap=3)
        ch = bot._client.get_channel(bot._channel_ids["general"])
        ch.history = _history_messages([_make_history_msg(bot=True) for _ in range(3)])

        discord_msg = AsyncMock()
        discord_msg.channel = ch
        discord_msg.channel.name = "general"
        discord_msg.channel.id = bot._channel_ids["general"]
        discord_msg.author = SimpleNamespace(id=2000, bot=False, display_name="User")
        discord_msg.mentions = []
        discord_msg.reference = None
        discord_msg.content = "hello"
        discord_msg.id = 9999
        discord_msg.reply = AsyncMock()

        message = Message(discord_msg, BOT_USER_ID)
        await bot.reply(message, "should not send")
        discord_msg.reply.assert_not_called()
