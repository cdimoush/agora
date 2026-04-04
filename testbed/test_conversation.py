"""Send a test message from citizen-a to citizen-b and observe responses.

Usage:
    python testbed/run.py &          # start testbed first
    python testbed/test_conversation.py

Citizen-a @mentions citizen-b with a random question. Only citizen-b
should respond (mention-only mode). Captures responses and prints results.
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

CITIZEN_A_TOKEN_ENV = "AGORA_CITIZEN_A_TOKEN"
CITIZEN_B_ID = 1490080381007954041  # agora-citizen-b
BOT_CHAT = "bot-chat"
RESPONSE_TIMEOUT = 45
COLLECT_EXTRA = 15  # seconds to collect additional responses after first


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

    token = os.environ.get(CITIZEN_A_TOKEN_ENV)
    if not token:
        logger.error("%s not set", CITIZEN_A_TOKEN_ENV)
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

        # Reset exchange cap
        deleted = 0
        async for msg in channel.history(limit=10):
            if msg.author.bot:
                try:
                    await msg.delete()
                    deleted += 1
                except (discord.Forbidden, discord.NotFound):
                    pass
        if deleted:
            logger.info("Deleted %d bot messages to reset exchange cap", deleted)
            await asyncio.sleep(1)

        # Pick a random question and send
        question = random.choice(QUESTIONS)
        text = f"<@{CITIZEN_B_ID}> {question}"
        send_time = time.time()
        logger.info("SENDING: %s", text)
        await channel.send(text)

        # Wait for first response
        try:
            await asyncio.wait_for(first_response.wait(), timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("No response within %ds — is the testbed running?", RESPONSE_TIMEOUT)
            return

        # Collect additional responses
        logger.info("Waiting %ds for additional responses...", COLLECT_EXTRA)
        await asyncio.sleep(COLLECT_EXTRA)

        # Report
        print()
        print("=" * 60)
        print(f"QUESTION: {question}")
        print(f"RESULTS: {len(responses)} response(s) in {time.time() - send_time:.1f}s")
        print("-" * 60)

        citizen_b_responded = False
        citizen_a_responded = False

        for r in responses:
            marker = ""
            if r["author_id"] == CITIZEN_B_ID:
                citizen_b_responded = True
                marker = " [EXPECTED — was @mentioned]"
            else:
                citizen_a_responded = True
                marker = " [UNEXPECTED — was NOT @mentioned]"

            print(f"  [{r['elapsed']:.1f}s] {r['author']}{marker}:")
            print(f"    {r['content'][:300]}")
            print()

        print("-" * 60)
        if citizen_b_responded and not citizen_a_responded:
            print("PASS: Only the @mentioned citizen responded")
        elif citizen_b_responded and citizen_a_responded:
            print("FAIL: citizen-a responded despite not being @mentioned (agora-knr bug)")
        elif not citizen_b_responded:
            print("FAIL: citizen-b did not respond despite being @mentioned")
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
