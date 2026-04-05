"""Tests for start()/stop()/wait_until_ready() lifecycle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.gateway import Agora
from agora.config import Config


BOT_USER_ID = 1000


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


class TestStart:
    @pytest.mark.asyncio
    async def test_start_sets_ready(self):
        bot = Agora(_make_config())

        # Mock _client.start to simulate connection + fire on_ready
        async def fake_start(token):
            bot._client.user = SimpleNamespace(id=BOT_USER_ID)
            bot._client.guilds = []
            await bot._on_ready()
            # Hang like a real connection
            await asyncio.Event().wait()

        bot._client = MagicMock()
        bot._client.user = None
        bot._client.start = fake_start
        bot._client.close = AsyncMock()
        bot._client.guilds = []

        # Monkeypatch token
        bot.config = _make_config()
        with patch.object(type(bot.config), 'token', property(lambda self: 'fake')):
            await bot.start()

        assert bot._ready_event.is_set()
        assert bot._client.user is not None
        await bot.stop()

    @pytest.mark.asyncio
    async def test_methods_work_after_start(self):
        bot = Agora(_make_config())

        async def fake_start(token):
            bot._client.user = SimpleNamespace(id=BOT_USER_ID)
            bot._client.guilds = []
            await bot._on_ready()
            await asyncio.Event().wait()

        bot._client = MagicMock()
        bot._client.user = None
        bot._client.start = fake_start
        bot._client.close = AsyncMock()
        bot._client.guilds = []

        with patch.object(type(bot.config), 'token', property(lambda self: 'fake')):
            await bot.start()

        # get_channels should work
        channels = bot.get_channels()
        assert "general" in channels
        await bot.stop()


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        bot = Agora(_make_config())

        async def fake_start(token):
            bot._client.user = SimpleNamespace(id=BOT_USER_ID)
            bot._client.guilds = []
            await bot._on_ready()
            await asyncio.Event().wait()

        bot._client = MagicMock()
        bot._client.user = None
        bot._client.start = fake_start
        bot._client.close = AsyncMock()
        bot._client.guilds = []

        with patch.object(type(bot.config), 'token', property(lambda self: 'fake')):
            await bot.start()
            await bot.stop()

        bot._client.close.assert_called_once()


class TestWaitUntilReady:
    @pytest.mark.asyncio
    async def test_wait_until_ready_blocks_then_resolves(self):
        bot = Agora(_make_config())
        resolved = []

        async def fake_start(token):
            bot._client.user = SimpleNamespace(id=BOT_USER_ID)
            bot._client.guilds = []
            await bot._on_ready()
            await asyncio.Event().wait()

        bot._client = MagicMock()
        bot._client.user = None
        bot._client.start = fake_start
        bot._client.close = AsyncMock()
        bot._client.guilds = []

        with patch.object(type(bot.config), 'token', property(lambda self: 'fake')):
            await bot.start()

        await bot.wait_until_ready()
        assert bot._ready_event.is_set()
        await bot.stop()


class TestConnectionGuardWithLifecycle:
    def test_methods_raise_before_start(self):
        bot = Agora(_make_config())
        with pytest.raises(RuntimeError, match="Not connected"):
            bot.get_channels()
