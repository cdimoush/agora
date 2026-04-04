"""Agora — AI agents on shared Discord servers."""

__version__ = "0.1.0"

from agora.config import Config
from agora.message import Message
from agora.bot import AgoraBot

__all__ = ["AgoraBot", "Config", "Message"]
