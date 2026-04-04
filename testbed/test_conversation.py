"""Send a test message from citizen-b (Rex) to citizen-a (Nova) and observe the volley.

Usage:
    python testbed/run.py &          # start testbed first
    python testbed/test_conversation.py

Uses the moderator to purge old messages (reset exchange cap), then a second
connection as citizen-b sends the opener @mentioning citizen-a. This way Nova
sees the message as coming from Rex (with Rex's Discord ID) and can @mention
him back to create a volley.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("test_conversation")

QUESTIONS = [
    "What's something you changed your mind about recently?",
    "Do you think people are generally getting smarter or dumber?",
    "What's a hill you'd die on that most people wouldn't care about?",
    "If you could only listen to one album for a year, what would it be?",
    "What's the most overrated thing everyone pretends to like?",
    "Do you think nostalgia is helpful or just a trap?",
    "What's something you wish more people understood about you?",
    "If you had to teach a class on anything, what would it be?",
    "What's the last thing that genuinely surprised you?",
    "Do you think it's better to be honest or kind when you can't be both?",
]

MOD_TOKEN_ENV = "AGORA_MOD_TOKEN"
CITIZEN_B_TOKEN_ENV = "AGORA_CITIZEN_B_TOKEN"
CITIZEN_A_ID = 1490079230191468807  # agora-citizen-a (Nova)
CITIZEN_B_ID = 1490080381007954041  # agora-citizen-b (Rex)
BOT_CHAT = "bot-chat"
RESPONSE_TIMEOUT = 45
COLLECT_EXTRA = 40  # long window to catch B -> A -> B


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


async def _purge_channel(token: str, channel_name: str) -> None:
    """Connect as moderator, delete all bot messages, disconnect."""
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    ready = asyncio.Event()

    @client.event
    async def on_ready():
        ready.set()

    task = asyncio.create_task(client.start(token))
    try:
        await asyncio.wait_for(ready.wait(), timeout=15)

        channel = None
        for guild in client.guilds:
            for ch in guild.text_channels:
                if ch.name == channel_name:
                    channel = ch
                    break

        if channel:
            deleted = 0
            async for msg in channel.history(limit=50):
                if msg.author.bot:
                    try:
                        await msg.delete()
                        deleted += 1
                    except (discord.Forbidden, discord.NotFound):
                        pass
            if deleted:
                logger.info("Purged %d bot messages from #%s", deleted, channel_name)
    finally:
        await client.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main():
    testbed_dir = Path(__file__).resolve().parent
    _load_env(testbed_dir / "citizen-a" / ".env")
    _load_env(testbed_dir / "citizen-b" / ".env")
    _load_env(testbed_dir / "moderator" / ".env")

    mod_token = os.environ.get(MOD_TOKEN_ENV)
    rex_token = os.environ.get(CITIZEN_B_TOKEN_ENV)
    if not mod_token or not rex_token:
        logger.error("Need both %s and %s", MOD_TOKEN_ENV, CITIZEN_B_TOKEN_ENV)
        sys.exit(1)

    # Phase 1: Moderator purges channel
    logger.info("Purging #%s via moderator...", BOT_CHAT)
    await _purge_channel(mod_token, BOT_CHAT)
    await asyncio.sleep(3)  # let Discord propagate

    # Phase 2: Rex sends the opener
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    ready = asyncio.Event()
    first_response = asyncio.Event()
    responses: list[dict] = []
    send_time = 0.0
    last_sent_text = ""

    @client.event
    async def on_ready():
        logger.info("Rex helper connected as %s", client.user)
        ready.set()

    @client.event
    async def on_message(msg):
        nonlocal send_time
        if (
            msg.channel.name == BOT_CHAT
            and msg.author.bot
            and msg.author.id in (CITIZEN_A_ID, CITIZEN_B_ID)
            and msg.content != last_sent_text  # skip echo of our own send
        ):
            elapsed = time.time() - send_time
            responses.append({
                "author": msg.author.display_name,
                "author_id": msg.author.id,
                "content": msg.content,
                "elapsed": elapsed,
            })
            logger.info(
                "[RESPONSE %.1fs] %s: %s",
                elapsed, msg.author.display_name, msg.content[:200],
            )
            first_response.set()

    task = asyncio.create_task(client.start(rex_token))

    try:
        await asyncio.wait_for(ready.wait(), timeout=15)

        # Find #bot-chat
        channel = None
        for guild in client.guilds:
            for ch in guild.text_channels:
                if ch.name == BOT_CHAT:
                    channel = ch
                    break
        if not channel:
            logger.error("#%s not found", BOT_CHAT)
            return

        # Rex @mentions Nova with a random question
        question = random.choice(QUESTIONS)
        text = f"<@{CITIZEN_A_ID}> {question}"
        last_sent_text = text
        send_time = time.time()
        logger.info("REX SENDS: %s", text)
        await channel.send(text)

        # Wait for first response
        try:
            await asyncio.wait_for(first_response.wait(), timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("No response within %ds — is the testbed running?", RESPONSE_TIMEOUT)
            return

        # Collect volleys — Nova should ask a follow-up @mentioning Rex,
        # Rex's running bot should respond back
        logger.info("Waiting %ds for volleys...", COLLECT_EXTRA)
        await asyncio.sleep(COLLECT_EXTRA)

        # Report
        print()
        print("=" * 60)
        print(f"REX ASKS: {question}")
        print(f"CONVERSATION: {len(responses)} message(s) in {time.time() - send_time:.1f}s")
        print("-" * 60)

        for i, r in enumerate(responses, 1):
            print(f"  [{r['elapsed']:.1f}s] {r['author']}:")
            print(f"    {r['content'][:300]}")
            print()

        print("-" * 60)
        if len(responses) >= 3:
            print(f"VOLLEY: {len(responses)} exchanges — full B -> A -> B achieved!")
        elif len(responses) >= 2:
            print(f"VOLLEY: {len(responses)} exchanges — conversation going")
        elif len(responses) == 1:
            print("SINGLE: Nova responded but no volley (didn't @mention Rex back)")
        else:
            print("FAIL: No responses")
        print("=" * 60)

    finally:
        await client.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
