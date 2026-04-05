"""Error types for Agora."""

from __future__ import annotations

from dataclasses import dataclass

from agora.message import Message


@dataclass
class ErrorContext:
    """Context passed to on_error describing where the error occurred."""

    stage: str  # 'on_message' or 'on_schedule'
    message: Message | None = None  # set for on_message errors
    channel: str | None = None  # set for on_schedule errors
