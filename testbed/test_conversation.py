"""Send a test message from citizen-b (Rex) to citizen-a (Nova) and observe the volley.

Usage:
    python testbed/run.py &          # start testbed first
    python testbed/test_conversation.py

Rex (direct, opinionated) @mentions Nova (curious, asks follow-ups) with a
random question. Nova should respond and @mention Rex back, creating a
natural conversation volley. Only @mentioned citizens should respond.
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

MOD_TOKEN_ENV = "AGORA_MOD_TOKEN"  # moderator has delete permissions
CITIZEN_A_ID = 1490079230191468807  # agora-citizen-a (Nova)
CITIZEN_B_ID = 1490080381007954041  # agora-citizen-b (Rex)
BOT_CHAT = "bot-chat"
RESPONSE_TIMEOUT = 45
COLLECT_EXTRA = 30  # longer window to catch volleys


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


async def main():
    testbed_dir = Path(__file__).resolve().parent
    _load_env(testbed_dir / "citizen-a" / ".env")
    _load_env(testbed_dir / "citizen-b" / ".env")
    _load_env(testbed_dir / "moderator" / ".env")

    token = os.environ.get(MOD_TOKEN_ENV)
    if not token:
        logger.error("%s not set", MOD_TOKEN_ENV)
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    ready = asyncio.Event()
    first_response = asyncio.Event()
    responses: list[dict] = []
    send_time = 0.0

    @client.event
    async def on_ready():
        logger.info("Helper connected as %s", client.user)
        ready.set()

    @client.event
    async def on_message(msg):
        nonlocal send_time
        if (
            msg.channel.name == BOT_CHAT
            and msg.author.bot
            and msg.author.id != client.user.id
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

    task = asyncio.create_task(client.start(token))

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

        # Reset exchange cap — purge ALL recent bot messages from history
        # The exchange cap counts consecutive bot messages in channel.history().
        # Deleting them ensures a clean slate for the test.
        deleted = 0
        async for msg in channel.history(limit=50):
            if msg.author.bot:
                try:
                    await msg.delete()
                    deleted += 1
                except (discord.Forbidden, discord.NotFound):
                    pass
        if deleted:
            logger.info("Purged %d bot messages to reset exchange cap", deleted)
        await asyncio.sleep(3)  # let Discord propagate deletions

        # Verify cap is clear
        bot_count = 0
        async for msg in channel.history(limit=6):
            if msg.author.bot:
                bot_count += 1
        if bot_count > 0:
            logger.warning("Still %d bot messages after purge — cap may fire", bot_count)

        # Rex (citizen-b) sends opener @mentioning Nova (citizen-a)
        question = random.choice(QUESTIONS)
        text = f"<@{CITIZEN_A_ID}> {question}"
        send_time = time.time()
        logger.info("SENDING as Rex: %s", text)
        await channel.send(text)

        # Wait for first response
        try:
            await asyncio.wait_for(first_response.wait(), timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("No response within %ds — is the testbed running?", RESPONSE_TIMEOUT)
            return

        # Collect volleys — Nova should ask a follow-up, Rex may reply
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
        if len(responses) >= 2:
            print(f"VOLLEY: {len(responses)} exchanges — conversation is alive")
        elif len(responses) == 1:
            print("SINGLE: Nova responded but no volley (Rex didn't get mentioned back)")
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
