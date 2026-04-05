"""Configuration loading and validation for Agora bots."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""


_VALID_CHANNEL_MODES = {"subscribe", "mention-only", "write-only"}
_VALID_RESPOND_MODES = {"mention-only", "all"}


@dataclass
class Config:
    token_env: str

    name: str = ""
    display_name: str = ""
    telemetry: bool = False
    respond_mode: str = "mention-only"
    channels: dict[str, str] = field(default_factory=dict)

    mention_resolution: bool = False
    mention_aliases: dict[str, str] = field(default_factory=dict)

    exchange_cap: int = 5

    jitter_seconds: tuple[float, float] = (1.0, 3.0)
    typing_indicator: bool = True
    reply_threading: bool = True
    max_response_length: int = 4000

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        """Load and validate config from a YAML file."""
        with open(path) as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ConfigError("Config file must be a YAML mapping")

        if "token_env" not in raw:
            raise ConfigError("token_env is required")

        # Silently consume rate_limit for backward compatibility
        raw.pop("rate_limit", None)

        # Normalise jitter_seconds from list to tuple
        jitter = raw.pop("jitter_seconds", None)
        if jitter is not None:
            if not isinstance(jitter, (list, tuple)) or len(jitter) != 2:
                raise ConfigError("jitter_seconds must be a 2-element list [min, max]")
            try:
                jitter = (float(jitter[0]), float(jitter[1]))
            except (TypeError, ValueError):
                raise ConfigError("jitter_seconds values must be numeric")
            if jitter[0] > jitter[1]:
                raise ConfigError("jitter_seconds min must be <= max")
            raw["jitter_seconds"] = jitter

        config = cls(**raw)
        config._validate()
        return config

    def _validate(self) -> None:
        """Validate field constraints."""
        for name, mode in self.channels.items():
            if mode not in _VALID_CHANNEL_MODES:
                raise ConfigError(
                    f"Invalid channel mode '{mode}' for '{name}'. "
                    f"Must be one of: {', '.join(sorted(_VALID_CHANNEL_MODES))}"
                )

        if self.exchange_cap < 1:
            raise ConfigError("exchange_cap must be >= 1")

        if self.max_response_length < 1:
            raise ConfigError("max_response_length must be >= 1")

        if self.respond_mode not in _VALID_RESPOND_MODES:
            raise ConfigError(
                f"Invalid respond_mode '{self.respond_mode}'. "
                f"Must be one of: {', '.join(sorted(_VALID_RESPOND_MODES))}"
            )

    @property
    def token(self) -> str:
        """Read the bot token from the environment variable named by token_env."""
        value = os.environ.get(self.token_env)
        if not value:
            raise ConfigError(
                f"Environment variable '{self.token_env}' is not set or empty"
            )
        return value
