"""Unit tests for agora.gateway — Agora dispatch pipeline with mocked discord.py."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.gateway import Agora as AgoraBot
from agora.config import Config


# ── Helpers ───────────────────────────────────────────────────

BOT_USER_ID = 1000


def _history_messages(messages):
    """Return an async iterator factory suitable for channel.history mock."""

    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg

    return _history


def _make_history_msg(*, bot=False):
    """Create a minimal message for channel history mocking."""
    author = SimpleNamespace(bot=bot, display_name="Bot" if bot else "Human")
    return SimpleNamespace(author=author)


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
    # Default empty history for exchange cap checker
    channel.history = _history_messages([])

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
        msg.reply.assert_called_once_with("response", mention_author=False)


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
        msg.reply.assert_called_once_with("hi", mention_author=False)


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
        msg.reply.assert_called_once_with("reply", mention_author=False)

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
        msg.reply.assert_called_once_with("threaded", mention_author=False)
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


class TestExchangeCapPipeline:
    @pytest.mark.asyncio
    async def test_exchange_cap_suppresses_response(self):
        """When cap is reached, should_respond is never called."""
        bot = _make_bot(exchange_cap=3)
        sr_called = []

        async def sr(m):
            sr_called.append(True)
            return True

        bot.should_respond = sr

        # 3 consecutive bot messages → cap reached
        history = [_make_history_msg(bot=True) for _ in range(3)]
        msg = _make_discord_msg(channel_name="general")
        msg.channel.history = _history_messages(history)

        await bot._on_message(msg)
        assert sr_called == []
        msg.reply.assert_not_called()
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_exchange_cap_allows_when_not_reached(self):
        """When under cap, pipeline continues to should_respond."""
        bot = _make_bot(exchange_cap=5)
        sr_called = []

        async def sr(m):
            sr_called.append(True)
            return False

        bot.should_respond = sr

        # 2 bot then 1 human → only 2 consecutive, under cap of 5
        history = [
            _make_history_msg(bot=True),
            _make_history_msg(bot=True),
            _make_history_msg(bot=False),
        ]
        msg = _make_discord_msg(channel_name="general")
        msg.channel.history = _history_messages(history)

        await bot._on_message(msg)
        assert sr_called == [True]

    @pytest.mark.asyncio
    async def test_exchange_cap_allows_after_human_message(self):
        """Human message resets counter — only recent consecutive bots count."""
        bot = _make_bot(exchange_cap=3)
        sr_called = []

        async def sr(m):
            sr_called.append(True)
            return False

        bot.should_respond = sr

        # 1 bot, 1 human, 3 bot (most recent first) → only 1 consecutive
        history = [
            _make_history_msg(bot=True),
            _make_history_msg(bot=False),
            _make_history_msg(bot=True),
            _make_history_msg(bot=True),
            _make_history_msg(bot=True),
        ]
        msg = _make_discord_msg(channel_name="general")
        msg.channel.history = _history_messages(history)

        await bot._on_message(msg)
        assert sr_called == [True]


class TestOnMessageAPI:
    """Tests for the new on_message API (replaces should_respond + generate_response)."""

    @pytest.mark.asyncio
    async def test_on_message_returns_response(self):
        """New API: on_message returning a string sends it."""
        from agora.gateway import Agora

        class NewAgent(Agora):
            async def on_message(self, message):
                return "new api reply"

        cfg = _make_config()
        bot = NewAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
        bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("new api reply", mention_author=False)

    @pytest.mark.asyncio
    async def test_on_message_returns_none(self):
        """New API: on_message returning None sends nothing."""
        from agora.gateway import Agora

        class SilentAgent(Agora):
            async def on_message(self, message):
                return None

        cfg = _make_config()
        bot = SilentAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
        bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_not_called()
        msg.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_message_exception_swallowed(self):
        """New API: on_message raising does not crash the pipeline."""
        from agora.gateway import Agora

        class BadAgent(Agora):
            async def on_message(self, message):
                raise RuntimeError("new api boom")

        cfg = _make_config()
        bot = BadAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
        bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_api_still_works(self):
        """Legacy API: should_respond + generate_response still dispatches."""
        bot = _make_bot()

        async def sr(m):
            return True

        async def gr(m):
            return "legacy reply"

        bot.should_respond = sr
        bot.generate_response = gr
        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("legacy reply", mention_author=False)

    @pytest.mark.asyncio
    async def test_on_message_wins_when_both_overridden(self):
        """When both APIs overridden, on_message takes precedence."""
        from agora.gateway import Agora

        class HybridAgent(Agora):
            async def should_respond(self, message):
                return True

            async def generate_response(self, message):
                return "legacy"

            async def on_message(self, message):
                return "new"

        cfg = _make_config()
        bot = HybridAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
        bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

        msg = _make_discord_msg(channel_name="general")
        await bot._on_message(msg)
        msg.reply.assert_called_once_with("new", mention_author=False)

    def test_method_detection_legacy(self):
        """Base Agora with no overrides uses legacy API."""
        from agora.gateway import Agora
        bot = Agora(_make_config())
        assert bot._use_legacy_api is True

    def test_method_detection_new(self):
        """Subclass overriding on_message uses new API."""
        from agora.gateway import Agora

        class NewAgent(Agora):
            async def on_message(self, message):
                return "hi"

        bot = NewAgent(_make_config())
        assert bot._use_legacy_api is False


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
