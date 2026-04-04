"""Message wrapper — thin layer over discord.Message."""

from __future__ import annotations


class Message:
    """Immutable view of a Discord message, tailored for agent decision-making.

    Shields operator code from discord.py internals. Operators never need
    to import discord to write should_respond / generate_response.
    """

    def __init__(self, discord_message, bot_user_id: int):
        self._msg = discord_message
        self._bot_user_id = bot_user_id

    @property
    def content(self) -> str:
        return self._msg.content or ""

    @property
    def author_name(self) -> str:
        return self._msg.author.display_name

    @property
    def author_id(self) -> int:
        return self._msg.author.id

    @property
    def is_bot(self) -> bool:
        return self._msg.author.bot

    @property
    def is_agent(self) -> bool:
        """True if the author has the Agora role or is a bot.

        Uses the same detection logic as the exchange cap checker:
        Agora role takes priority, falls back to the bot flag.
        """
        if hasattr(self._msg.author, "roles"):
            for role in self._msg.author.roles:
                if role.name == "Agora":
                    return True
        return self._msg.author.bot

    @property
    def is_mention(self) -> bool:
        return any(u.id == self._bot_user_id for u in self._msg.mentions)

    @property
    def channel_name(self) -> str:
        return self._msg.channel.name

    @property
    def channel_id(self) -> int:
        return self._msg.channel.id

    @property
    def id(self) -> int:
        return self._msg.id

    @property
    def reference_id(self) -> int | None:
        ref = self._msg.reference
        if ref is not None:
            return ref.message_id
        return None
