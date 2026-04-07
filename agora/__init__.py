"""Agora — AI agents on shared Discord servers."""

from __future__ import annotations

import warnings

__version__ = "0.1.0"

from agora.config import Config
from agora.context import (
    ContainerContext,
    ContextError,
    ContainerCrashed,
    ExecResult,
    ExecutionContext,
    ImageBuildError,
    LocalContext,
    RuntimeNotFound,
    detect_runtime,
)
from agora.errors import ErrorContext
from agora.message import Message
from agora.gateway import Agora
from agora.telemetry import (
    Span,
    TelemetryProcessor,
    LogProcessor,
    ReplayProcessor,
    TestProcessor,
)


def __getattr__(name: str):
    if name == "AgoraBot":
        warnings.warn(
            "AgoraBot is deprecated, use Agora instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return Agora
    raise AttributeError(f"module 'agora' has no attribute {name!r}")


__all__ = [
    "Agora",
    "AgoraBot",
    "Config",
    "ContextError",
    "ContainerContext",
    "ContainerCrashed",
    "ErrorContext",
    "ExecResult",
    "ExecutionContext",
    "ImageBuildError",
    "LocalContext",
    "Message",
    "RuntimeNotFound",
    "detect_runtime",
    "Span",
    "TelemetryProcessor",
    "LogProcessor",
    "ReplayProcessor",
    "TestProcessor",
]
