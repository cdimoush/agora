"""Tests for agora.safety — ExchangeCapChecker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agora.safety import ExchangeCapChecker


# ── Helpers ───────────────────────────────────────────────────


def _make_msg(*, bot=False, roles=None, age_minutes=0):
    """Create a minimal message-like object for ExchangeCapChecker."""
    author_kwargs = {"bot": bot, "display_name": "Agent" if bot else "Human"}
    if roles is not None:
        author_kwargs["roles"] = [SimpleNamespace(name=r) for r in roles]
    author = SimpleNamespace(**author_kwargs)
    created_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return SimpleNamespace(author=author, created_at=created_at)


def _make_channel(messages):
    """Create a mock channel whose .history() yields the given messages."""
    channel = AsyncMock()
    channel.name = "test-channel"

    async def _history(limit=None):
        for msg in messages[:limit]:
            yield msg

    channel.history = _history
    return channel


# ── Tests ─────────────────────────────────────────────────────


class TestExchangeCapNotReached:
    @pytest.mark.asyncio
    async def test_mixed_messages_under_cap(self):
        """3 bot messages then 1 human, cap=5 → not capped."""
        msgs = [
            _make_msg(bot=True),
            _make_msg(bot=True),
            _make_msg(bot=True),
            _make_msg(bot=False),
        ]
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel(msgs)) is False


class TestExchangeCapReached:
    @pytest.mark.asyncio
    async def test_all_bot_messages_at_cap(self):
        """5 consecutive bot messages, cap=5 → capped."""
        msgs = [_make_msg(bot=True) for _ in range(5)]
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel(msgs)) is True

    @pytest.mark.asyncio
    async def test_cap_exactly_at_threshold(self):
        """5 bot messages with cap=5 → capped (>= not >)."""
        msgs = [_make_msg(bot=True) for _ in range(6)]
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel(msgs)) is True


class TestHumanResets:
    @pytest.mark.asyncio
    async def test_human_message_resets_counter(self):
        """2 bot, 1 human, 3 bot (most recent first) → only 2 consecutive."""
        msgs = [
            _make_msg(bot=True),
            _make_msg(bot=True),
            _make_msg(bot=False),  # human resets
            _make_msg(bot=True),
            _make_msg(bot=True),
            _make_msg(bot=True),
        ]
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel(msgs)) is False


class TestOwnMessagesCount:
    @pytest.mark.asyncio
    async def test_own_messages_count_toward_cap(self):
        """5 bot messages (some from 'self') all count — no skipping."""
        msgs = [_make_msg(bot=True) for _ in range(5)]
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel(msgs)) is True


class TestAgentDetection:
    def test_agora_role_detected(self):
        """Author with Agora role and bot=False → is agent."""
        msg = _make_msg(bot=False, roles=["Agora"])
        assert ExchangeCapChecker._is_agent(msg) is True

    def test_bot_flag_detected(self):
        """Author with bot=True but no roles → is agent."""
        msg = _make_msg(bot=True)
        assert ExchangeCapChecker._is_agent(msg) is True

    def test_human_not_detected(self):
        """Author with bot=False and no Agora role → not agent."""
        msg = _make_msg(bot=False, roles=["Member", "Admin"])
        assert ExchangeCapChecker._is_agent(msg) is False

    def test_human_no_roles_attr(self):
        """Author with bot=False and no roles attribute → not agent."""
        msg = _make_msg(bot=False)
        assert ExchangeCapChecker._is_agent(msg) is False


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_channel(self):
        """No messages in channel → not capped."""
        checker = ExchangeCapChecker(cap=5)
        assert await checker.is_capped(_make_channel([])) is False

    @pytest.mark.asyncio
    async def test_cap_of_one(self):
        """Cap=1, one bot message → capped."""
        msgs = [_make_msg(bot=True)]
        checker = ExchangeCapChecker(cap=1)
        assert await checker.is_capped(_make_channel(msgs)) is True

    @pytest.mark.asyncio
    async def test_agora_role_counts_in_cap(self):
        """Messages from Agora-role authors count toward cap."""
        msgs = [_make_msg(bot=False, roles=["Agora"]) for _ in range(3)]
        checker = ExchangeCapChecker(cap=3)
        assert await checker.is_capped(_make_channel(msgs)) is True


class TestTimeWindow:
    """Time-based reset of the exchange cap."""

    @pytest.mark.asyncio
    async def test_old_messages_not_counted(self):
        """Bot messages older than the window don't count toward cap."""
        msgs = [_make_msg(bot=True, age_minutes=90) for _ in range(5)]
        checker = ExchangeCapChecker(cap=5, window_minutes=60)
        assert await checker.is_capped(_make_channel(msgs)) is False

    @pytest.mark.asyncio
    async def test_recent_messages_still_capped(self):
        """Bot messages within the window still trigger cap."""
        msgs = [_make_msg(bot=True, age_minutes=5) for _ in range(5)]
        checker = ExchangeCapChecker(cap=5, window_minutes=60)
        assert await checker.is_capped(_make_channel(msgs)) is True

    @pytest.mark.asyncio
    async def test_mixed_age_partial_count(self):
        """Only recent messages count: 2 recent + 3 old, cap=5 → not capped."""
        msgs = [
            _make_msg(bot=True, age_minutes=5),
            _make_msg(bot=True, age_minutes=10),
            _make_msg(bot=True, age_minutes=90),  # outside window
            _make_msg(bot=True, age_minutes=100),
            _make_msg(bot=True, age_minutes=120),
        ]
        checker = ExchangeCapChecker(cap=5, window_minutes=60)
        assert await checker.is_capped(_make_channel(msgs)) is False

    @pytest.mark.asyncio
    async def test_default_window_is_60_minutes(self):
        """Default window is 60 minutes."""
        checker = ExchangeCapChecker(cap=5)
        from datetime import timedelta
        assert checker.window == timedelta(minutes=60)
