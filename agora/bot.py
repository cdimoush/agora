"""AgoraBot base class — the core dispatch pipeline for Agora agents."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Self

import discord

from agora.chunker import chunk_message
from agora.config import Config
from agora.message import Message

logger = logging.getLogger("agora")


class AgoraBot:
    """Base class for Agora agents.

    Subclass and override should_respond() and generate_response().
    """

    def __init__(self, config: Config):
        self.config = config

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        self._client = discord.Client(intents=intents)

        self._channel_map: dict[str, str] = {}
        self._channel_ids: dict[str, int] = {}

        self._client.event(self._on_ready)
        self._client.event(self._on_message)

    # ── Public: operators override these ──────────────────────

    async def should_respond(self, message: Message) -> bool:
        """Return True to trigger response generation.
        Default: respond to @mentions only."""
        return message.is_mention

    async def generate_response(self, message: Message) -> str | None:
        """Return response text or None. Called only when should_respond() is True."""
        return None

    # ── Public: lifecycle ─────────────────────────────────────

    @classmethod
    def from_config(cls, path: str) -> Self:
        """Create an instance (or subclass instance) from a YAML config file."""
        config = Config.from_yaml(path)
        return cls(config)

    def run(self) -> None:
        """Start the bot. Blocks until stopped."""
        logger.info("Starting Agora bot...")
        self._client.run(self.config.token)

    # ── Internal: discord.py event handlers ───────────────────

    async def _on_ready(self) -> None:
        logger.info(
            f"Connected as {self._client.user} (ID: {self._client.user.id})"
        )
        self._resolve_channels()
        self._check_intents()

    async def _on_message(self, discord_message: discord.Message) -> None:
        """Main dispatch pipeline."""
        # Step 1: Ignore own messages
        if discord_message.author.id == self._client.user.id:
            return

        # Step 2: Check channel config
        channel_name = discord_message.channel.name
        mode = self._get_channel_mode(channel_name)
        if mode is None or mode == "write-only":
            return

        # Step 3: Build Message wrapper
        message = Message(discord_message, self._client.user.id)

        # Step 4: Enforce mention-only mode
        if mode == "mention-only" and not message.is_mention:
            return

        # Step 5: Operator's should_respond
        try:
            if not await self.should_respond(message):
                return
        except Exception as e:
            logger.error(f"should_respond raised: {e}")
            return

        # Step 6: Jitter delay
        jitter = random.uniform(*self.config.jitter_seconds)
        await asyncio.sleep(jitter)

        # Step 7: Typing indicator
        if self.config.typing_indicator:
            await discord_message.channel.trigger_typing()

        # Step 8: Operator's generate_response
        try:
            response = await self.generate_response(message)
        except Exception as e:
            logger.error(f"generate_response raised: {e}")
            return

        if response is None:
            return

        # Step 9: Truncate and chunk
        response = response[: self.config.max_response_length]
        chunks = chunk_message(response)

        # Step 10: Send (reply-threaded for first chunk if enabled)
        for i, chunk in enumerate(chunks):
            if i == 0 and self.config.reply_threading:
                await discord_message.reply(chunk)
            else:
                await discord_message.channel.send(chunk)

    # ── Internal: helpers ─────────────────────────────────────

    def _resolve_channels(self) -> None:
        for guild in self._client.guilds:
            for channel in guild.text_channels:
                if channel.name in self.config.channels:
                    self._channel_map[channel.name] = self.config.channels[
                        channel.name
                    ]
                    self._channel_ids[channel.name] = channel.id

        for name in self.config.channels:
            if name not in self._channel_map:
                logger.warning(
                    f"Channel '{name}' in config but not found on server"
                )

    def _get_channel_mode(self, channel_name: str) -> str | None:
        if not self.config.channels:
            return "mention-only"
        return self._channel_map.get(channel_name)

    def _check_intents(self) -> None:
        self._intent_warned = False
