"""Tests for agora.message — Message wrapper over discord.Message."""

from types import SimpleNamespace

import pytest

from agora.message import Message


def _make_discord_msg(
    *,
    content="hello",
    author_name="Alice",
    author_id=111,
    author_bot=False,
    channel_name="general",
    channel_id=222,
    msg_id=333,
    mentions=None,
    reference_message_id=None,
):
    author = SimpleNamespace(
        display_name=author_name, id=author_id, bot=author_bot
    )
    channel = SimpleNamespace(name=channel_name, id=channel_id)
    ref = None
    if reference_message_id is not None:
        ref = SimpleNamespace(message_id=reference_message_id)
    return SimpleNamespace(
        content=content,
        author=author,
        channel=channel,
        id=msg_id,
        mentions=mentions or [],
        reference=ref,
    )


BOT_USER_ID = 999


class TestMessageProperties:
    def test_content(self):
        msg = Message(_make_discord_msg(content="test message"), BOT_USER_ID)
        assert msg.content == "test message"

    def test_author_name(self):
        msg = Message(_make_discord_msg(author_name="Bob"), BOT_USER_ID)
        assert msg.author_name == "Bob"

    def test_author_id(self):
        msg = Message(_make_discord_msg(author_id=42), BOT_USER_ID)
        assert msg.author_id == 42

    def test_is_bot_true(self):
        msg = Message(_make_discord_msg(author_bot=True), BOT_USER_ID)
        assert msg.is_bot is True

    def test_is_bot_false(self):
        msg = Message(_make_discord_msg(author_bot=False), BOT_USER_ID)
        assert msg.is_bot is False

    def test_channel_name(self):
        msg = Message(_make_discord_msg(channel_name="bot-chat"), BOT_USER_ID)
        assert msg.channel_name == "bot-chat"

    def test_channel_id(self):
        msg = Message(_make_discord_msg(channel_id=555), BOT_USER_ID)
        assert msg.channel_id == 555

    def test_id(self):
        msg = Message(_make_discord_msg(msg_id=777), BOT_USER_ID)
        assert msg.id == 777


class TestIsMention:
    def test_mentioned(self):
        bot_user = SimpleNamespace(id=BOT_USER_ID)
        dm = _make_discord_msg(mentions=[bot_user])
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_mention is True

    def test_not_mentioned(self):
        other_user = SimpleNamespace(id=12345)
        dm = _make_discord_msg(mentions=[other_user])
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_mention is False

    def test_no_mentions(self):
        dm = _make_discord_msg(mentions=[])
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_mention is False


class TestIsAgent:
    def test_is_agent_with_agora_role(self):
        dm = _make_discord_msg(author_bot=False)
        dm.author.roles = [SimpleNamespace(name="Agora")]
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_agent is True

    def test_is_agent_with_bot_flag(self):
        dm = _make_discord_msg(author_bot=True)
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_agent is True

    def test_is_agent_for_human(self):
        dm = _make_discord_msg(author_bot=False)
        msg = Message(dm, BOT_USER_ID)
        assert msg.is_agent is False


class TestEdgeCases:
    def test_empty_content(self):
        msg = Message(_make_discord_msg(content=""), BOT_USER_ID)
        assert msg.content == ""

    def test_none_content(self):
        msg = Message(_make_discord_msg(content=None), BOT_USER_ID)
        assert msg.content == ""
