"""Backward-compatible shim — AgoraBot is now agora.gateway.Agora.

Importing from this module triggers a DeprecationWarning.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "agora.bot is deprecated, import from agora.gateway instead",
    DeprecationWarning,
    stacklevel=2,
)

from agora.gateway import Agora as AgoraBot  # noqa: E402, F401

__all__ = ["AgoraBot"]
