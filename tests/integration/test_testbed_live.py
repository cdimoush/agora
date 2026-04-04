"""Live integration tests for the Phase 3 testbed (citizens + moderator).

Requires:
  - AGORA_CITIZEN_A_TOKEN, AGORA_CITIZEN_B_TOKEN, AGORA_MOD_TOKEN env vars
  - Bots invited to AgoraGenesis with #bot-chat and #mod-log channels
  - MESSAGE_CONTENT intent enabled for all bots
  - Run with: pytest tests/integration/test_testbed_live.py --live -v

These tests are slow (30+ seconds) — they start real bots and wait for
Claude subprocess responses.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
from pathlib import Path

import discord
import pytest
import pytest_asyncio

# Ensure repo root importable
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from agora import Config

logger = logging.getLogger("agora.test.testbed")

TIMEOUT = 45  # seconds — Claude responses can take a while
BOT_CHAT = "bot-chat"
MOD_LOG = "mod-log"


def _import_citizen():
    """Import CitizenBot from the hyphenated citizen-a directory."""
    spec = importlib.util.spec_from_file_location(
        "citizen_a", repo_root / "testbed" / "citizen-a" / "citizen.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CitizenBot


def _import_moderator():
    """Import ModeratorBot from the moderator directory."""
    spec = importlib.util.spec_from_file_location(
        "mod", repo_root / "testbed" / "moderator" / "mod.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ModeratorBot


CitizenBot = _import_citizen()
ModeratorBot = _import_moderator()


# ── Helpers ──────────────────────────────────────────────────


def _load_env(path: Path) -> None:
    """Source a .env file into os.environ."""
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


async def _start_bot(bot, timeout: float = TIMEOUT):
    """Start a bot and wait for on_ready, returning the background task."""
    ready = asyncio.Event()
    original = bot._on_ready

    async def patched():
        await original()
        ready.set()

    bot._on_ready = patched
    task = asyncio.get_event_loop().create_task(bot._client.start(bot.config.token))
    await asyncio.wait_for(ready.wait(), timeout=timeout)
    return task


async def _stop_bot(bot, task):
    """Gracefully stop a bot."""
    await bot._client.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def load_env_files():
    """Load .env files from testbed directories."""
    testbed = repo_root / "testbed"
    _load_env(testbed / "citizen-a" / ".env")
    _load_env(testbed / "citizen-b" / ".env")
    _load_env(testbed / "moderator" / ".env")


@pytest.fixture(scope="session")
def citizen_a_token():
    token = os.environ.get("AGORA_CITIZEN_A_TOKEN")
    if not token:
        pytest.skip("AGORA_CITIZEN_A_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def mod_token():
    token = os.environ.get("AGORA_MOD_TOKEN")
    if not token:
        pytest.skip("AGORA_MOD_TOKEN not set")
    return token


@pytest_asyncio.fixture()
async def citizen_a(citizen_a_token):
    """Start citizen-a, yield it, then shut it down."""
    bot = CitizenBot.from_config(
        str(repo_root / "testbed" / "citizen-a" / "agent.yaml")
    )
    task = await _start_bot(bot)
    try:
        yield bot
    finally:
        await _stop_bot(bot, task)


@pytest_asyncio.fixture()
async def helper_client(mod_token):
    """A helper Discord client for sending test messages.

    Uses the moderator token since we need a separate identity from the
    citizen bots to trigger responses.
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
        await asyncio.wait_for(ready.wait(), timeout=TIMEOUT)
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
    async def test_citizen_connects(self, citizen_a):
        """Citizen-a connects to Discord and sees #bot-chat."""
        assert citizen_a._client.user is not None
        channel = _find_channel(citizen_a._client, BOT_CHAT)
        assert channel is not None, f"#{BOT_CHAT} not found"

    @pytest.mark.asyncio
    async def test_citizen_responds_to_mention(self, citizen_a, helper_client):
        """Citizen-a responds when @mentioned in #bot-chat."""
        channel = _find_channel(helper_client, BOT_CHAT)
        assert channel is not None

        citizen_user = citizen_a._client.user

        # Send @mention
        mention_text = f"<@{citizen_user.id}> hello, what do you think about music?"
        await channel.send(mention_text)

        # Wait for citizen to respond
        response_received = asyncio.Event()
        response_content = []

        @citizen_a._client.event
        async def on_message(msg):
            # Look for a message from the citizen (not from the helper)
            if msg.author.id == citizen_user.id and msg.channel.name == BOT_CHAT:
                response_content.append(msg.content)
                response_received.set()

        try:
            await asyncio.wait_for(response_received.wait(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            pytest.fail("Citizen did not respond within timeout")

        assert len(response_content) > 0
        assert len(response_content[0]) > 0
        assert len(response_content[0]) < 500
        logger.info("Citizen responded: %s", response_content[0][:100])


class TestExchangeCap:
    @pytest.mark.asyncio
    async def test_moderator_warns_on_cap(self, citizen_a, helper_client):
        """Moderator posts warning in #mod-log when exchange cap is reached.

        This is a manual verification test — it confirms the moderator
        connects and can see #mod-log. Full cap testing requires two
        citizens and enough back-and-forth to trigger the cap.
        """
        # Start moderator alongside the citizen
        mod = ModeratorBot.from_config(
            str(repo_root / "testbed" / "moderator" / "agent.yaml")
        )
        mod_task = await _start_bot(mod)

        try:
            assert mod._client.user is not None
            mod_log = _find_channel(mod._client, MOD_LOG)
            assert mod_log is not None, f"#{MOD_LOG} not found"
            logger.info(
                "Moderator online as %s, monitoring #%s",
                mod._client.user,
                MOD_LOG,
            )
        finally:
            await _stop_bot(mod, mod_task)
