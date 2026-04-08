"""Tests for agora.cli — init, templates, registry, source resolution."""

from __future__ import annotations

import json
import os
import py_compile

import pytest

from agora.cli import init_agent, _slugify, _to_class_name, _validate_name, _resolve_agora_source


class TestInitAgent:
    def test_creates_directory_with_expected_files(self, tmp_path):
        path = init_agent("my-bot", path=tmp_path / "my-bot", template="echo")
        assert path.exists()
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / ".agora").exists()

    def test_citizen_template_has_all_files(self, tmp_path):
        path = init_agent("nova", path=tmp_path / "nova")
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / "mind.py").exists()
        assert (path / "CLAUDE.md").exists()
        assert (path / "Dockerfile").exists()
        assert (path / ".env.example").exists()
        assert (path / ".gitignore").exists()
        assert (path / ".agora").exists()

    def test_agent_py_compiles(self, tmp_path):
        path = init_agent("test-agent", path=tmp_path / "test-agent", template="echo")
        py_compile.compile(str(path / "agent.py"), doraise=True)

    def test_citizen_agent_py_compiles(self, tmp_path):
        path = init_agent("test-citizen", path=tmp_path / "test-citizen")
        py_compile.compile(str(path / "agent.py"), doraise=True)

    def test_citizen_mind_py_compiles(self, tmp_path):
        path = init_agent("test-mind", path=tmp_path / "test-mind")
        py_compile.compile(str(path / "mind.py"), doraise=True)

    def test_agent_yaml_loads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake")
        path = init_agent("yaml-test", path=tmp_path / "yaml-test", template="echo")
        from agora.config import Config
        cfg = Config.from_yaml(path / "agent.yaml")
        assert cfg.token_env == "DISCORD_BOT_TOKEN"

    def test_raises_if_dir_exists(self, tmp_path):
        init_agent("dup-test", path=tmp_path / "dup-test", template="echo")
        with pytest.raises(FileExistsError):
            init_agent("dup-test", path=tmp_path / "dup-test", template="echo")

    def test_substitutions_applied(self, tmp_path):
        path = init_agent("my-bot", path=tmp_path / "my-bot", template="echo")
        content = (path / "agent.py").read_text()
        assert "{{name}}" not in content
        assert "{{class_name}}" not in content
        assert "my-bot" in content or "my_bot" in content

    def test_agora_metadata(self, tmp_path):
        path = init_agent("meta-test", path=tmp_path / "meta-test")
        agora_file = path / ".agora"
        assert agora_file.exists()
        content = agora_file.read_text()
        assert "template: citizen" in content
        assert "agora_version:" in content
        assert "created:" in content

    def test_default_path_uses_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = init_agent("auto-dir")
        assert path == tmp_path / "auto-dir"
        assert path.exists()

    def test_unknown_template_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown template"):
            init_agent("bad", path=tmp_path / "bad", template="nonexistent")


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


class TestValidateName:
    def test_valid_name(self):
        assert _validate_name("my-bot") == "my-bot"

    def test_valid_underscore(self):
        assert _validate_name("my_bot") == "my_bot"

    def test_slugifies(self):
        assert _validate_name("my bot") == "my_bot"


class TestTemplates:
    def test_list_templates(self):
        from agora.templates import list_templates
        templates = list_templates()
        assert "echo" in templates
        assert "citizen" in templates

    def test_get_template_dir(self):
        from agora.templates import get_template_dir
        d = get_template_dir("echo")
        assert d.is_dir()
        assert (d / "agent.py").exists()

    def test_unknown_template_raises(self):
        from agora.templates import get_template_dir
        with pytest.raises(ValueError, match="Unknown template"):
            get_template_dir("nonexistent")

    def test_manifest_valid_json(self):
        from agora.templates import TEMPLATES_DIR
        manifest = TEMPLATES_DIR / "manifest.json"
        data = json.loads(manifest.read_text())
        assert "templates" in data
        for name, meta in data["templates"].items():
            assert "description" in meta
            assert "container" in meta


class TestRegistry:
    def test_register_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agora.registry.REGISTRY_DIR", tmp_path)
        monkeypatch.setattr("agora.registry.REGISTRY_PATH", tmp_path / "registry.json")
        from agora.registry import register, load_registry
        register("nova", "/tmp/nova", "citizen")
        reg = load_registry()
        assert "nova" in reg["citizens"]
        assert reg["citizens"]["nova"]["path"] == "/tmp/nova"

    def test_name_collision(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agora.registry.REGISTRY_DIR", tmp_path)
        monkeypatch.setattr("agora.registry.REGISTRY_PATH", tmp_path / "registry.json")
        from agora.registry import register
        register("nova", "/tmp/nova", "citizen")
        with pytest.raises(ValueError, match="already registered"):
            register("nova", "/tmp/other-nova", "citizen")

    def test_same_path_is_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agora.registry.REGISTRY_DIR", tmp_path)
        monkeypatch.setattr("agora.registry.REGISTRY_PATH", tmp_path / "registry.json")
        from agora.registry import register
        register("nova", "/tmp/nova", "citizen")
        register("nova", "/tmp/nova", "citizen")  # No error

    def test_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agora.registry.REGISTRY_DIR", tmp_path)
        monkeypatch.setattr("agora.registry.REGISTRY_PATH", tmp_path / "registry.json")
        from agora.registry import load_registry
        reg = load_registry()
        assert reg == {"citizens": {}}


class TestResolveAgoraSource:
    def test_env_var(self, tmp_path, monkeypatch):
        # Create a fake agora source
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'agora'\n")
        monkeypatch.setenv("AGORA_SOURCE", str(tmp_path))
        result = _resolve_agora_source()
        assert result == tmp_path

    def test_cli_override(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'agora'\n")
        monkeypatch.delenv("AGORA_SOURCE", raising=False)
        result = _resolve_agora_source(str(tmp_path))
        assert result == tmp_path

    def test_missing_pyproject_exits(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGORA_SOURCE", str(tmp_path))
        with pytest.raises(SystemExit):
            _resolve_agora_source()

    def test_no_source_exits(self, monkeypatch):
        monkeypatch.delenv("AGORA_SOURCE", raising=False)
        with pytest.raises(SystemExit):
            _resolve_agora_source()

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        # Create a fake source in a specific path
        src = tmp_path / "agora-src"
        src.mkdir()
        (src / "pyproject.toml").write_text("[project]\nname = 'agora'\n")
        monkeypatch.setenv("AGORA_SOURCE", str(src))
        result = _resolve_agora_source()
        assert result == src
