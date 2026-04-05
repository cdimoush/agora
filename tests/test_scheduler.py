"""Tests for scheduler.py + on_schedule integration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.gateway import Agora
from agora.config import Config
from agora.scheduler import parse_interval, SchedulerTask


# ── parse_interval tests ─────────────────────────────────────


class TestParseInterval:
    def test_hours(self):
        assert parse_interval("1h") == 3600.0

    def test_minutes(self):
        assert parse_interval("30m") == 1800.0

    def test_seconds(self):
        assert parse_interval("5s") == 5.0

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("abc")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("100")


# ── Config validation ────────────────────────────────────────


class TestConfigScheduleValidation:
    def test_valid_schedule_accepted(self):
        cfg = Config(token_env="TOK", schedule="1h")
        cfg._validate()  # should not raise

    def test_invalid_schedule_rejected(self):
        from agora.config import ConfigError
        cfg = Config(token_env="TOK", schedule="bad")
        with pytest.raises(ConfigError):
            cfg._validate()


# ── on_schedule dispatch ─────────────────────────────────────

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


def _make_bot(**config_overrides) -> Agora:
    cfg = _make_config(**config_overrides)
    bot = Agora(cfg)
    mock_client = MagicMock()
    mock_client.user = SimpleNamespace(id=BOT_USER_ID)
    mock_client.guilds = []
    bot._client = mock_client
    bot._channel_map = {name: mode for name, mode in cfg.channels.items()}
    bot._channel_ids = {name: i for i, name in enumerate(cfg.channels)}

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


class TestOnScheduleTick:
    @pytest.mark.asyncio
    async def test_on_schedule_returning_dict_sends(self):
        class ScheduledAgent(Agora):
            async def on_schedule(self):
                return {"general": "hello from schedule"}

        cfg = _make_config()
        bot = ScheduledAgent(cfg)
        mock_client = MagicMock()
        mock_client.user = SimpleNamespace(id=BOT_USER_ID)
        mock_client.guilds = []
        bot._client = mock_client
        bot._channel_map = {"general": "subscribe", "announce": "write-only"}
        bot._channel_ids = {"general": 0, "announce": 1}

        ch = AsyncMock()
        ch.history = _history_messages([])
        ch.send = AsyncMock()
        mock_client.get_channel = lambda cid: ch

        await bot._on_schedule_tick()
        ch.send.assert_called_once_with("hello from schedule")

    @pytest.mark.asyncio
    async def test_on_schedule_returning_none_no_sends(self):
        bot = _make_bot()
        await bot._on_schedule_tick()
        # No channel sends should have happened
        for idx in bot._channel_ids.values():
            ch = bot._client.get_channel(idx)
            ch.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_schedule_error_routes_to_on_error(self):
        errors_seen = []

        class BrokenSchedule(Agora):
            async def on_schedule(self):
                raise RuntimeError("schedule boom")

            async def on_error(self, error, context):
                errors_seen.append((error, context))
                return None

        cfg = _make_config()
        bot = BrokenSchedule(cfg)
        bot._client = MagicMock()
        bot._client.user = SimpleNamespace(id=BOT_USER_ID)
        bot._client.guilds = []

        await bot._on_schedule_tick()
        assert len(errors_seen) == 1
        assert errors_seen[0][1].stage == "on_schedule"

    @pytest.mark.asyncio
    async def test_on_schedule_invalid_channel_logged(self):
        class BadChannel(Agora):
            async def on_schedule(self):
                return {"nonexistent": "hello"}

        cfg = _make_config()
        bot = BadChannel(cfg)
        bot._client = MagicMock()
        bot._client.user = SimpleNamespace(id=BOT_USER_ID)
        bot._client.guilds = []
        bot._channel_map = {"general": "subscribe"}
        bot._channel_ids = {"general": 0}

        # Should not raise (error is logged)
        await bot._on_schedule_tick()
