"""Exchange cap — the safety layer.

The exchange cap prevents infinite bot-to-bot loops by limiting
consecutive bot messages in a channel. When the cap is reached,
the bot suppresses its response. A human message resets the counter.

This is cooperative, client-side safety. It protects the operator's
wallet. Server-side enforcement (moderator) is a separate concern.
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger("agora")

AGORA_ROLE_NAME = "Agora"


class ExchangeCapChecker:
    """Reads Discord channel history to count consecutive bot messages.

    Each agent independently reads the same shared state (Discord's message
    history) and arrives at the same conclusion. No distributed coordination.
    """

    def __init__(self, cap: int):
        self.cap = cap

    async def is_capped(self, channel: discord.TextChannel) -> bool:
        """Return True if the exchange cap has been reached.

        Algorithm:
        1. Fetch the last (cap + 1) messages from the channel
        2. Walk from most recent backwards
        3. Count consecutive messages where author is a bot or has Agora role
        4. If count >= cap: suppress
        5. If a non-bot human message is found: counter resets, proceed
        """
        messages = []
        async for msg in channel.history(limit=self.cap + 1):
            messages.append(msg)

        consecutive_bot = 0
        for msg in messages:
            if self._is_agent(msg):
                consecutive_bot += 1
            else:
                break  # Human message resets counter

        if consecutive_bot >= self.cap:
            logger.info(
                f"Exchange cap reached in #{channel.name} "
                f"({consecutive_bot} consecutive bot messages, cap={self.cap})"
            )
            return True
        return False

    @staticmethod
    def _is_agent(message: discord.Message) -> bool:
        """Check if a message author is an Agora agent.

        Priority: Agora role > bot flag. The Agora role allows non-bot
        accounts to be recognized as agents. Falls back to the bot flag
        for agents that don't have the role assigned.
        """
        if hasattr(message.author, "roles"):
            for role in message.author.roles:
                if role.name == AGORA_ROLE_NAME:
                    return True
        return message.author.bot
