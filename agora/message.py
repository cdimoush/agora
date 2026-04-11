"""Message wrapper — thin layer over discord.Message."""

from __future__ import annotations

from pathlib import Path

import discord


class Attachment:
    """Wrapper for a Discord file attachment."""

    __slots__ = ("filename", "url", "content_type", "size", "_discord_attachment")

    def __init__(self, discord_attachment: discord.Attachment):
        self.filename: str = discord_attachment.filename
        self.url: str = discord_attachment.url
        self.content_type: str = discord_attachment.content_type or ""
        self.size: int = discord_attachment.size
        self._discord_attachment = discord_attachment

    async def save(self, path: str | Path) -> Path:
        """Download and save the attachment to a local file."""
        path = Path(path)
        await self._discord_attachment.save(path)
        return path

    def __repr__(self) -> str:
        return f"Attachment({self.filename!r}, {self.size} bytes)"


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
    def is_dm(self) -> bool:
        """True if this message was sent via DM."""
        return isinstance(self._msg.channel, discord.DMChannel)

    @property
    def channel_name(self) -> str:
        if isinstance(self._msg.channel, discord.DMChannel):
            return "dm"
        return self._msg.channel.name

    @property
    def channel_id(self) -> int:
        return self._msg.channel.id

    @property
    def id(self) -> int:
        return self._msg.id

    @property
    def attachments(self) -> list[Attachment]:
        """File attachments on this message (images, audio, documents)."""
        return [Attachment(a) for a in self._msg.attachments]

