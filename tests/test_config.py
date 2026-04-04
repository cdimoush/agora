"""Tests for agora.config — Config loading, validation, and defaults."""

import os
import textwrap
from pathlib import Path

import pytest

from agora.config import Config, ConfigError


@pytest.fixture()
def tmp_yaml(tmp_path):
    """Helper that writes YAML content to a temp file and returns its path."""

    def _write(content: str) -> Path:
        p = tmp_path / "agent.yaml"
        p.write_text(textwrap.dedent(content))
        return p

    return _write


class TestConfigFromYaml:
    def test_loads_valid_config(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            channels:
              general: subscribe
              announcements: write-only
            exchange_cap: 3
            jitter_seconds: [0.5, 2.0]
            typing_indicator: false
            reply_threading: false
            max_response_length: 8000
        """)
        cfg = Config.from_yaml(path)
        assert cfg.token_env == "MY_TOKEN"
        assert cfg.channels == {"general": "subscribe", "announcements": "write-only"}
        assert cfg.exchange_cap == 3
        assert cfg.jitter_seconds == (0.5, 2.0)
        assert cfg.typing_indicator is False
        assert cfg.reply_threading is False
        assert cfg.max_response_length == 8000

    def test_defaults_applied(self, tmp_yaml):
        path = tmp_yaml("token_env: MY_TOKEN\n")
        cfg = Config.from_yaml(path)
        assert cfg.channels == {}
        assert cfg.exchange_cap == 5
        assert cfg.jitter_seconds == (1.0, 3.0)
        assert cfg.typing_indicator is True
        assert cfg.reply_threading is True
        assert cfg.max_response_length == 4000

    def test_rate_limit_silently_ignored(self, tmp_yaml):
        """Old configs with rate_limit should still load without error."""
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            rate_limit:
              per_channel_per_hour: 20
              global_per_hour: 60
        """)
        cfg = Config.from_yaml(path)
        assert cfg.token_env == "MY_TOKEN"
        assert not hasattr(cfg, "rate_limit")

    def test_missing_token_env_raises(self, tmp_yaml):
        path = tmp_yaml("channels: {}\n")
        with pytest.raises(ConfigError, match="token_env is required"):
            Config.from_yaml(path)

    def test_invalid_channel_mode_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            channels:
              general: read-only
        """)
        with pytest.raises(ConfigError, match="Invalid channel mode"):
            Config.from_yaml(path)

    def test_exchange_cap_zero_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            exchange_cap: 0
        """)
        with pytest.raises(ConfigError, match="exchange_cap must be >= 1"):
            Config.from_yaml(path)

    def test_exchange_cap_negative_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            exchange_cap: -1
        """)
        with pytest.raises(ConfigError, match="exchange_cap must be >= 1"):
            Config.from_yaml(path)

    def test_jitter_min_greater_than_max_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            jitter_seconds: [5.0, 1.0]
        """)
        with pytest.raises(ConfigError, match="min must be <= max"):
            Config.from_yaml(path)

    def test_jitter_non_numeric_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            jitter_seconds: [fast, slow]
        """)
        with pytest.raises(ConfigError, match="numeric"):
            Config.from_yaml(path)

    def test_jitter_wrong_length_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            jitter_seconds: [1.0]
        """)
        with pytest.raises(ConfigError, match="2-element"):
            Config.from_yaml(path)

    def test_max_response_length_zero_raises(self, tmp_yaml):
        path = tmp_yaml("""\
            token_env: MY_TOKEN
            max_response_length: 0
        """)
        with pytest.raises(ConfigError, match="max_response_length must be >= 1"):
            Config.from_yaml(path)


class TestConfigToken:
    def test_token_reads_env_var(self, tmp_yaml, monkeypatch):
        monkeypatch.setenv("TEST_TOKEN_123", "my-secret-token")
        path = tmp_yaml("token_env: TEST_TOKEN_123\n")
        cfg = Config.from_yaml(path)
        assert cfg.token == "my-secret-token"

    def test_token_raises_when_env_unset(self, tmp_yaml, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        path = tmp_yaml("token_env: NONEXISTENT_VAR\n")
        cfg = Config.from_yaml(path)
        with pytest.raises(ConfigError, match="not set or empty"):
            _ = cfg.token

    def test_token_raises_when_env_empty(self, tmp_yaml, monkeypatch):
        monkeypatch.setenv("EMPTY_TOKEN", "")
        path = tmp_yaml("token_env: EMPTY_TOKEN\n")
        cfg = Config.from_yaml(path)
        with pytest.raises(ConfigError, match="not set or empty"):
            _ = cfg.token
