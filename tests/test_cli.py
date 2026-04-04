"""Tests for agora.cli — init scaffolding command."""

from __future__ import annotations

import os
import py_compile
import stat

import pytest

from agora.cli import init_agent, _slugify, _to_class_name
from agora.config import Config


class TestInitAgent:
    def test_creates_directory_with_expected_files(self, tmp_path):
        path = init_agent("my-bot", base_dir=tmp_path)
        assert path.exists()
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / "run.sh").exists()

    def test_agent_py_compiles(self, tmp_path):
        path = init_agent("test-agent", base_dir=tmp_path)
        py_compile.compile(str(path / "agent.py"), doraise=True)

    def test_agent_yaml_loads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake")
        path = init_agent("yaml-test", base_dir=tmp_path)
        cfg = Config.from_yaml(path / "agent.yaml")
        assert cfg.token_env == "DISCORD_BOT_TOKEN"

    def test_run_sh_is_executable(self, tmp_path):
        path = init_agent("exec-test", base_dir=tmp_path)
        run_sh = path / "run.sh"
        assert run_sh.stat().st_mode & stat.S_IXUSR

    def test_raises_if_dir_exists(self, tmp_path):
        init_agent("dup-test", base_dir=tmp_path)
        with pytest.raises(FileExistsError):
            init_agent("dup-test", base_dir=tmp_path)

    def test_handles_special_chars_in_name(self, tmp_path):
        path = init_agent("my bot! @2", base_dir=tmp_path)
        assert path.exists()
        # Directory name should be slugified
        assert " " not in path.name
        assert "!" not in path.name
        assert "@" not in path.name


class TestSlugify:
    def test_basic(self):
        assert _slugify("my-bot") == "my-bot"

    def test_spaces(self):
        assert _slugify("my bot") == "my_bot"

    def test_special_chars(self):
        assert _slugify("bot!@#$") == "bot"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _slugify("!@#$")


class TestToClassName:
    def test_hyphenated(self):
        assert _to_class_name("my-bot") == "MyBot"

    def test_underscored(self):
        assert _to_class_name("my_bot") == "MyBot"

    def test_single_word(self):
        assert _to_class_name("bot") == "Bot"
