"""ModeratorBot — warns in #mod-log when exchange cap is reached."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agora import Agora, Message

logger = logging.getLogger("agora.moderator")


class ModeratorBot(Agora):
    """Server-side observer. Watches for exchange cap violations, warns in mod-log."""

    async def should_respond(self, message: Message) -> bool:
        """Monitor all bot messages."""
        return message.is_agent

    async def generate_response(self, message: Message) -> str | None:
        """Check exchange cap. If violated, warn in mod-log. Return None always."""
        channel = self._client.get_channel(message.channel_id)
        if channel is None:
            return None

        if await self._exchange_cap.is_capped(channel):
            await self._warn_mod_log(
                f"Exchange cap reached in #{message.channel_name} "
                f"({self.config.exchange_cap} consecutive bot messages)"
            )

        return None  # Moderator never posts visible responses

    async def _warn_mod_log(self, text: str) -> None:
        """Post a warning to #mod-log."""
        for guild in self._client.guilds:
            for ch in guild.text_channels:
                if ch.name == "mod-log":
                    await ch.send(f"[MOD] {text}")
                    return
        logger.warning("No #mod-log channel found: %s", text)


if __name__ == "__main__":
    config_path = str(Path(__file__).resolve().parent / "agent.yaml")
    bot = ModeratorBot.from_config(config_path)
    bot.run()
