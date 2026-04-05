"""Tests for deprecation warnings on legacy imports and API usage."""

from __future__ import annotations

import importlib
import warnings

import pytest


class TestDeprecationWarnings:
    def test_import_agorabot_from_agora(self):
        """from agora import AgoraBot triggers DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Force fresh lookup via __getattr__
            import agora
            _ = agora.AgoraBot
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)
                                     and "AgoraBot" in str(x.message)]
            assert len(deprecation_warnings) >= 1, f"Expected AgoraBot deprecation warning, got: {w}"

    def test_import_from_agora_bot_module(self):
        """import agora.bot triggers DeprecationWarning."""
        # Unload the module so import triggers the warning again
        import sys
        sys.modules.pop("agora.bot", None)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import agora.bot  # noqa: F401
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)
                                     and "agora.bot" in str(x.message)]
            assert len(deprecation_warnings) >= 1, f"Expected agora.bot deprecation warning, got: {w}"

    def test_agorabot_is_agora(self):
        """AgoraBot is the same class as Agora."""
        from agora.gateway import Agora
        import agora
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert agora.AgoraBot is Agora

    def test_legacy_api_detection(self):
        """Subclass using should_respond/generate_response is detected as legacy."""
        from agora.gateway import Agora
        from agora.config import Config

        class LegacyAgent(Agora):
            async def should_respond(self, message):
                return True
            async def generate_response(self, message):
                return "hi"

        cfg = Config(token_env="TOK")
        bot = LegacyAgent(cfg)
        assert bot._use_legacy_api is True

    def test_new_api_detection(self):
        """Subclass using on_message is detected as new API."""
        from agora.gateway import Agora
        from agora.config import Config

        class NewAgent(Agora):
            async def on_message(self, message):
                return "hi"

        cfg = Config(token_env="TOK")
        bot = NewAgent(cfg)
        assert bot._use_legacy_api is False
