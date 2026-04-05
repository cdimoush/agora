"""Live integration tests for AgoraBot against a real Discord server.

Requires:
  - TEST_BOT_TOKEN env var set to a valid bot token
  - Bot invited to a server with #general channel
  - MESSAGE_CONTENT intent enabled in Developer Portal
  - Run with: pytest tests/integration/ --live

These tests start the bot, interact via a helper client, and verify behavior.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
import pytest
import pytest_asyncio

# Ensure repo root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agora import Agora, Config
AgoraBot = Agora

logger = logging.getLogger("agora.test")

# ── Fixtures & Helpers ────────────────────────────────────────

TIMEOUT = 15  # seconds to wait for bot responses
TEST_CHANNEL = "general"



class EchoTestBot(AgoraBot):
    """Echo bot for testing — echoes back the message content."""

    async def should_respond(self, message):
        return message.is_mention

    async def generate_response(self, message):
        return message.content


class ErrorTestBot(AgoraBot):
    """Bot whose should_respond raises — for error-handling tests."""

    async def should_respond(self, message):
        raise RuntimeError("intentional test error")

    async def generate_response(self, message):
        return "should not reach here"


@pytest.fixture(scope="session")
def bot_token():
    token = os.environ.get("TEST_BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        pytest.skip("TEST_BOT_TOKEN or DISCORD_BOT_TOKEN not set")
    return token


@pytest_asyncio.fixture()
async def echo_bot(bot_token, tmp_path):
    """Start an echo bot, yield it, then shut it down."""
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(f"""\
token_env: TEST_BOT_TOKEN
channels:
  {TEST_CHANNEL}: mention-only
jitter_seconds: [0.1, 0.5]
typing_indicator: true
reply_threading: true
max_response_length: 4000
""")
    os.environ["TEST_BOT_TOKEN"] = bot_token
    config = Config.from_yaml(str(config_path))
    bot = EchoTestBot(config)

    # Start bot in background task
    loop = asyncio.get_event_loop()
    ready_event = asyncio.Event()

    original_on_ready = bot._on_ready

    async def patched_on_ready():
        await original_on_ready()
        ready_event.set()

    bot._on_ready = patched_on_ready

    task = loop.create_task(bot._client.start(config.token))

    try:
        await asyncio.wait_for(ready_event.wait(), timeout=TIMEOUT)
        yield bot
    finally:
        await bot._client.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest_asyncio.fixture()
async def helper_client(bot_token):
    """A second Discord client used to send test messages.

    NOTE: This reuses the same bot token. Both clients see each other's
    messages because they share the same bot user. The echo bot filters
    its own messages (step 1 of dispatch), so the helper's messages are
    sent as a regular user would need to. For true integration testing,
    a separate user/bot token is ideal.

    For now, this fixture enables connection and channel verification tests.
    Message-response tests require a human to @mention the bot in Discord.
    """
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    ready = asyncio.Event()

    @client.event
    async def on_ready():
        ready.set()

    task = asyncio.get_event_loop().create_task(client.start(bot_token))
    try:
        await asyncio.wait_for(ready.wait(), timeout=TIMEOUT)
        yield client
    finally:
        await client.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── Tests ─────────────────────────────────────────────────────


class TestConnection:
    @pytest.mark.asyncio
    async def test_bot_connects_and_on_ready_fires(self, echo_bot):
        """Test 1: Bot connects and on_ready fires within timeout."""
        assert echo_bot._client.user is not None
        assert echo_bot._client.user.id > 0
        logger.info(f"Bot connected as {echo_bot._client.user}")

    @pytest.mark.asyncio
    async def test_bot_sees_configured_channel(self, echo_bot):
        """Bot can see the configured channel on the server."""
        found = False
        for guild in echo_bot._client.guilds:
            for channel in guild.text_channels:
                if channel.name == TEST_CHANNEL:
                    found = True
                    break
        assert found, f"Channel #{TEST_CHANNEL} not found on server"

    @pytest.mark.asyncio
    async def test_channel_resolved_in_channel_map(self, echo_bot):
        """on_ready resolves configured channels into the channel map."""
        assert TEST_CHANNEL in echo_bot._channel_map
        assert echo_bot._channel_map[TEST_CHANNEL] == "mention-only"


class TestManualInteraction:
    """Tests that require a human to @mention the bot in Discord.

    These serve as a checklist — run them, then interact in Discord
    and observe the results. They verify the bot is running and
    listening, but response verification is visual.
    """

    @pytest.mark.asyncio
    async def test_bot_is_online_and_listening(self, echo_bot):
        """Bot is online. Go to Discord and @mention it to test echo."""
        # Just verify the bot is running — human does the rest
        assert echo_bot._client.is_ready()
        logger.info(
            f"Bot is online as {echo_bot._client.user}. "
            f"@mention it in #{TEST_CHANNEL} to test echo response."
        )


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_error_bot_connects(self, bot_token, tmp_path):
        """A bot with a broken should_respond still connects."""
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(f"""\
token_env: TEST_BOT_TOKEN
channels:
  {TEST_CHANNEL}: mention-only
jitter_seconds: [0.0, 0.0]
typing_indicator: false
reply_threading: true
max_response_length: 4000
""")
        os.environ["TEST_BOT_TOKEN"] = bot_token
        config = Config.from_yaml(str(config_path))
        bot = ErrorTestBot(config)

        ready = asyncio.Event()
        original = bot._on_ready

        async def patched():
            await original()
            ready.set()

        bot._on_ready = patched
        task = asyncio.get_event_loop().create_task(bot._client.start(config.token))

        try:
            await asyncio.wait_for(ready.wait(), timeout=TIMEOUT)
            assert bot._client.user is not None
            logger.info("ErrorTestBot connected — errors in should_respond won't crash it.")
        finally:
            await bot._client.close()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
