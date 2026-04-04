"""Message wrapper — thin layer over discord.Message."""

from __future__ import annotations


class Message:
    """Immutable view of a Discord message, tailored for agent decision-making."""

    def __init__(self, discord_message, bot_user_id: int):
        self._msg = discord_message
        self._bot_user_id = bot_user_id
