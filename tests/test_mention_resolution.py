"""Unit tests for mention resolution (@displayname → <@ID>)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora.gateway import Agora as AgoraBot
from agora.config import Config


BOT_USER_ID = 1000
NOVA_ID = 2000
REX_ID = 3000
HUMAN_ID = 4000


def _make_config(**overrides) -> Config:
    defaults = dict(
        token_env="TEST_TOKEN",
        name="test-bot",
        channels={"general": "subscribe"},
        mention_resolution=True,
        mention_aliases={"Nova": "agora-citizen-a", "Rex": "agora-citizen-b"},
        exchange_cap=5,
        jitter_seconds=(0.0, 0.0),
        typing_indicator=False,
        reply_threading=False,
        max_response_length=4000,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_bot_with_member_map(**config_overrides):
    """Create a bot and manually set up the member map (no Discord connection)."""
    config = _make_config(**config_overrides)
    bot = AgoraBot(config)

    # Manually populate member map as _resolve_members() would
    bot._member_map = {
        "agora-citizen-a": NOVA_ID,
        "agora-citizen-b": REX_ID,
        "nova": NOVA_ID,
        "rex": REX_ID,
        "roy batty": HUMAN_ID,
        "offworldnexus": HUMAN_ID,
    }

    # Build the regex pattern
    names = sorted(bot._member_map.keys(), key=len, reverse=True)
    escaped = [re.escape(n) for n in names]
    bot._mention_pattern = re.compile(
        r"@(" + "|".join(escaped) + r")(?=[\s,!?.\"\']|$)",
        re.IGNORECASE,
    )

    return bot


class TestResolveMentions:
    def test_basic_resolution(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("@Nova what do you think?")
        assert result == f"<@{NOVA_ID}> what do you think?"

    def test_persona_alias(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("hey @Rex tell me more")
        assert result == f"hey <@{REX_ID}> tell me more"

    def test_display_name(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("@agora-citizen-a are you there?")
        assert result == f"<@{NOVA_ID}> are you there?"

    def test_multiple_mentions(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("@Nova and @Rex both")
        assert f"<@{NOVA_ID}>" in result
        assert f"<@{REX_ID}>" in result

    def test_unknown_name_unchanged(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("@pizza is great")
        assert result == "@pizza is great"

    def test_email_not_matched(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("email me at user@example.com")
        assert result == "email me at user@example.com"

    def test_case_insensitive(self):
        bot = _make_bot_with_member_map()
        r1 = bot._resolve_mentions("@Nova hi")
        r2 = bot._resolve_mentions("@nova hi")
        r3 = bot._resolve_mentions("@NOVA hi")
        assert r1 == r2 == r3 == f"<@{NOVA_ID}> hi"

    def test_multiword_name(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("hey @Roy Batty check this")
        assert result == f"hey <@{HUMAN_ID}> check this"

    def test_no_member_map(self):
        config = _make_config(mention_resolution=False)
        bot = AgoraBot(config)
        result = bot._resolve_mentions("@Nova hi")
        assert result == "@Nova hi"  # no pattern, unchanged

    def test_mention_at_end_of_text(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("what do you think @Rex")
        assert result == f"what do you think <@{REX_ID}>"

    def test_mention_with_punctuation(self):
        bot = _make_bot_with_member_map()
        result = bot._resolve_mentions("@Nova, what about you?")
        assert result == f"<@{NOVA_ID}>, what about you?"

    def test_already_resolved_not_double_processed(self):
        bot = _make_bot_with_member_map()
        text = f"<@{NOVA_ID}> already mentioned"
        result = bot._resolve_mentions(text)
        assert result == text  # no change


class TestMentionResolutionConfig:
    def test_members_intent_on_when_enabled(self):
        config = _make_config(mention_resolution=True)
        bot = AgoraBot(config)
        assert bot._client._connection._intents.members

    def test_members_intent_off_when_disabled(self):
        config = _make_config(mention_resolution=False)
        bot = AgoraBot(config)
        assert not bot._client._connection._intents.members
