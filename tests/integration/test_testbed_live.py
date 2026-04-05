"""Live integration tests — runs against an already-running testbed.

Prerequisite:
    python testbed/run.py   # start bots in another terminal

Then run:
    .venv/bin/python -m pytest tests/integration/test_testbed_live.py --live -v

These tests connect a helper client (via the moderator token), inject
messages into #bot-chat, and verify the running citizens respond.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import discord
import pytest
import pytest_asyncio

repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

logger = logging.getLogger("agora.test.testbed")

RESPONSE_TIMEOUT = 60  # seconds to wait for a citizen response
CONNECT_TIMEOUT = 15
BOT_CHAT = "bot-chat"
MOD_LOG = "mod-log"


# ── Helpers ──────────────────────────────────────────────────


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _find_channel(client: discord.Client, name: str) -> discord.TextChannel | None:
    for guild in client.guilds:
        for ch in guild.text_channels:
            if ch.name == name:
                return ch
    return None


async def _reset_exchange_cap(channel: discord.TextChannel, needed: int = 6) -> int:
    """Delete recent bot messages to reset the exchange cap.

    Returns the number of messages deleted.
    """
    deleted = 0
    async for msg in channel.history(limit=needed):
        if msg.author.bot:
            try:
                await msg.delete()
                deleted += 1
            except discord.Forbidden:
                logger.warning("No permission to delete messages — exchange cap may block")
                break
            except discord.NotFound:
                pass
    if deleted:
        logger.info("Deleted %d bot messages to reset exchange cap", deleted)
    return deleted


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def load_env_files():
    testbed = repo_root / "testbed"
    _load_env(testbed / "citizen-a" / ".env")
    _load_env(testbed / "citizen-b" / ".env")
    _load_env(testbed / "moderator" / ".env")


@pytest.fixture(scope="session")
def mod_token():
    token = os.environ.get("AGORA_MOD_TOKEN")
    if not token:
        pytest.skip("AGORA_MOD_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def citizen_a_id():
    """The user ID of citizen-a, so we can @mention it."""
    # Read from env or discover at runtime
    return os.environ.get("AGORA_CITIZEN_A_ID")


@pytest_asyncio.fixture()
async def helper(mod_token):
    """A Discord client for injecting test messages.

    Uses the moderator token — a second connection alongside the running
    moderator bot. Both see all messages. The helper sends, the running
    citizens respond.
    """
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    ready = asyncio.Event()

    @client.event
    async def on_ready():
        ready.set()

    task = asyncio.get_event_loop().create_task(client.start(mod_token))
    try:
        await asyncio.wait_for(ready.wait(), timeout=CONNECT_TIMEOUT)
        logger.info("Helper connected as %s", client.user)
        yield client
    finally:
        await client.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── Tests ────────────────────────────────────────────────────


class TestCitizenResponds:

    @pytest.mark.asyncio
    async def test_helper_sees_bot_chat(self, helper):
        """Helper client can see #bot-chat on the server."""
        channel = _find_channel(helper, BOT_CHAT)
        assert channel is not None, f"#{BOT_CHAT} not found on server"

    @pytest.mark.asyncio
    async def test_citizen_responds_to_message(self, helper, citizen_a_id):
        """Send a message in #bot-chat and verify a citizen responds.

        If citizen_a_id is set, @mentions citizen-a specifically.
        Otherwise sends an unmentioned message that any citizen may pick up.
        """
        channel = _find_channel(helper, BOT_CHAT)
        assert channel is not None

        # Reset exchange cap so citizens aren't blocked
        await _reset_exchange_cap(channel)
        await asyncio.sleep(1)  # brief pause after deletions

        # Build test message
        prompt = "What's your favorite way to spend a rainy day?"
        if citizen_a_id:
            text = f"<@{citizen_a_id}> {prompt}"
        else:
            text = prompt

        # Set up response listener BEFORE sending
        responses: list[dict] = []
        response_received = asyncio.Event()
        helper_user_id = helper.user.id

        @helper.event
        async def on_message(msg):
            # Collect messages from other bots in #bot-chat
            if (msg.channel.name == BOT_CHAT
                    and msg.author.bot
                    and msg.author.id != helper_user_id):
                responses.append({
                    "author": msg.author.display_name,
                    "content": msg.content,
                    "elapsed": time.time() - send_time,
                })
                logger.info("[RESPONSE %.1fs] %s: %s",
                            responses[-1]["elapsed"],
                            msg.author.display_name,
                            msg.content[:200])
                response_received.set()

        # Send the test message
        send_time = time.time()
        logger.info("SENDING: %s", text)
        await channel.send(text)

        # Wait for at least one response
        try:
            await asyncio.wait_for(response_received.wait(), timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            pytest.fail(
                f"No citizen response within {RESPONSE_TIMEOUT}s. "
                "Is the testbed running? (python testbed/run.py)"
            )

        # Wait a bit more to collect additional responses
        await asyncio.sleep(10)

        # Verify
        assert len(responses) > 0, "Expected at least one citizen response"
        first = responses[0]
        assert len(first["content"]) > 0, "Response was empty"
        assert len(first["content"]) < 2000, "Response exceeded max length"

        logger.info("=" * 50)
        logger.info("RESULTS: %d response(s)", len(responses))
        for r in responses:
            logger.info("  [%.1fs] %s: %s", r["elapsed"], r["author"], r["content"][:150])
        logger.info("=" * 50)


class TestModLog:

    @pytest.mark.asyncio
    async def test_helper_sees_mod_log(self, helper):
        """Helper client can see #mod-log on the server."""
        channel = _find_channel(helper, MOD_LOG)
        assert channel is not None, f"#{MOD_LOG} not found on server"

    @pytest.mark.asyncio
    async def test_mod_log_has_history(self, helper):
        """Check if #mod-log has any moderator warnings from past runs."""
        channel = _find_channel(helper, MOD_LOG)
        assert channel is not None

        mod_messages = []
        async for msg in channel.history(limit=20):
            if "[MOD]" in msg.content:
                mod_messages.append(msg.content)

        if mod_messages:
            logger.info("Found %d moderator warnings in #mod-log", len(mod_messages))
            for m in mod_messages[:5]:
                logger.info("  %s", m)
        else:
            logger.info("No moderator warnings found yet (expected if cap hasn't fired)")
