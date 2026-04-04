"""Unit tests for agora.bot — AgoraBot dispatch pipeline with mocked discord.py."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.bot import AgoraBot
from agora.config import Config


# ── Helpers ───────────────────────────────────────────────────

BOT_USER_ID = 1000


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        channels={"general": "subscribe", "announce": "write-only"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),  # no jitter in tests
        typing_indicator=False,
        reply_threading=True,
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
    reference=None,
):
    author = SimpleNamespace(id=author_id, bot=author_bot, display_name="User")
    channel = AsyncMock()
    channel.name = channel_name
    channel.id = 500
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=AsyncMock())

    msg = AsyncMock()
    msg.author = author
    msg.channel = channel
    msg.content = content
    msg.id = 9999
    msg.mentions = mentions or []
    msg.reference = reference
    msg.reply = AsyncMock()
    return msg


def _make_bot(config=None, **config_overrides) -> AgoraBot:
    cfg = config or _make_config(**config_overrides)
    bot = AgoraBot(cfg)
    # Replace the real discord.Client with a mock so we can set .user
    mock_client = MagicMock()
    mock_client.user = SimpleNamespace(id=BOT_USER_ID)
    mock_client.guilds = []
    bot._client = mock_client
    # Simulate that on_ready resolved channels
    bot._channel_map = {
        name: mode for name, mode in cfg.channels.items()
    }
    bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}
    return bot


# ── Tests ─────────────────────────────────────────────────────


class TestIgnoreFiltering:
    @pytest.mark.asyncio
    async def test_ignores_own_messages(self):
        bot = _make_bot()
        msg = _make_discord_msg(author_id=BOT_USER_ID)
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unconfigured_channel(self):
        bot = _make_bot()
        msg = _make_discord_msg(channel_name="random")
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_write_only_channel(self):
        bot = _make_bot()
        msg = _make_discord_msg(channel_name="announce")
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()


class TestMentionOnlyMode:
    @pytest.mark.asyncio
    async def test_ignores_non_mention_in_mention_only(self):
        bot = _make_bot(channels={"general": "mention-only"})
        msg = _make_discord_msg(channel_name="general", mentions=[])
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_mention_in_mention_only(self):
        bot = _make_bot(channels={"general": "mention-only"})
        bot_mention = SimpleNamespace(id=BOT_USER_ID)
        msg = _make_discord_msg(
            channel_name="general", mentions=[bot_mention]
        )

        async def gen_resp(m):
            return "response"

        bot.generate_response = gen_resp
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("response")


class TestEmptyChannelsConfig:
    @pytest.mark.asyncio
    async def test_empty_channels_treats_all_as_mention_only(self):
        bot = _make_bot(channels={})
        # Non-mention should be ignored
        msg = _make_discord_msg(channel_name="any-channel", mentions=[])
        await bot._on_message(msg)
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_channels_responds_to_mention(self):
        bot = _make_bot(channels={})
        bot_mention = SimpleNamespace(id=BOT_USER_ID)
        msg = _make_discord_msg(
            channel_name="any-channel", mentions=[bot_mention]
        )

        async def gen_resp(m):
            return "hi"

        bot.generate_response = gen_resp
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("hi")


class TestShouldRespondDispatch:
    @pytest.mark.asyncio
    async def test_calls_should_respond_for_subscribe(self):
        bot = _make_bot()
        called = []

        async def sr(m):
            called.append(True)
            return False

        bot.should_respond = sr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_calls_generate_when_should_respond_true(self):
        bot = _make_bot()
        gen_called = []

        async def sr(m):
            return True

        async def gr(m):
            gen_called.append(True)
            return "reply"

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        assert gen_called == [True]
        msg.reply.assert_called_once_with("reply")

    @pytest.mark.asyncio
    async def test_skips_generate_when_should_respond_false(self):
        bot = _make_bot()
        gen_called = []

        async def sr(m):
            return False

        async def gr(m):
            gen_called.append(True)
            return "reply"

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        assert gen_called == []
        msg.reply.assert_not_called()


class TestResponseSending:
    @pytest.mark.asyncio
    async def test_reply_threading_enabled(self):
        bot = _make_bot(reply_threading=True)

        async def sr(m):
            return True

        async def gr(m):
            return "threaded"

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("threaded")
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_threading_disabled(self):
        bot = _make_bot(reply_threading=False)

        async def sr(m):
            return True

        async def gr(m):
            return "flat"

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_not_called()
        msg.channel.send.assert_called_once_with("flat")

    @pytest.mark.asyncio
    async def test_chunks_long_responses(self):
        bot = _make_bot(reply_threading=True)

        async def sr(m):
            return True

        async def gr(m):
            return "a" * 3000

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        # First chunk via reply, rest via send
        msg.reply.assert_called_once()
        assert msg.channel.send.call_count >= 1

    @pytest.mark.asyncio
    async def test_none_response_sends_nothing(self):
        bot = _make_bot()

        async def sr(m):
            return True

        async def gr(m):
            return None

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_not_called()
        msg.channel.send.assert_not_called()


class TestExceptionHandling:
    @pytest.mark.asyncio
    async def test_should_respond_exception_swallowed(self):
        bot = _make_bot()

        async def sr(m):
            raise RuntimeError("boom")

        bot.should_respond = sr
        msg = _make_discord_msg(channel_name="general")
        # Should not raise
        await bot._on_message(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_response_exception_swallowed(self):
        bot = _make_bot()

        async def sr(m):
            return True

        async def gr(m):
            raise ValueError("api timeout")

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        # Should not raise
        await bot._on_message(msg)
        msg.reply.assert_not_called()


class TestFromConfig:
    def test_returns_correct_subclass(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_TOK", "fake-token")
        cfg_path = tmp_path / "agent.yaml"
        cfg_path.write_text("token_env: MY_TOK\n")

        class MyAgent(AgoraBot):
            pass

        instance = MyAgent.from_config(str(cfg_path))
        assert isinstance(instance, MyAgent)
        assert type(instance) is MyAgent
        assert instance.config.token_env == "MY_TOK"
