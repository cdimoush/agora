"""Tests for fleet management — multi-agent init, compose-based fleet commands.

These tests validate the full fleet workflow: initializing multiple agents
from different templates, compose service generation, and fleet commands.
No actual containers are started — container operations are mocked.
"""

from __future__ import annotations

import py_compile

import pytest

from agora.cli import (
    init_agent, fleet_start, fleet_stop, fleet_status,
    compose_service_block, _scan_fleet, _ensure_compose,
)


class TestMultiAgentInit:
    """Test initializing a fleet of agents from different templates."""

    def test_init_citizen_produces_runnable_dir(self, tmp_path):
        path = init_agent("nova", path=tmp_path / "nova", template="citizen")
        # All required files present
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / "mind.py").exists()
        assert (path / "Dockerfile").exists()
        assert (path / "CLAUDE.md").exists()
        # Compiles
        py_compile.compile(str(path / "agent.py"), doraise=True)
        py_compile.compile(str(path / "mind.py"), doraise=True)
        # Substitutions applied
        yaml_content = (path / "agent.yaml").read_text()
        assert "AGORA_NOVA_TOKEN" in yaml_content
        assert "Nova" in yaml_content  # display_name
        assert "{{" not in yaml_content

    def test_init_moderator_produces_runnable_dir(self, tmp_path):
        path = init_agent("mod", path=tmp_path / "mod", template="moderator")
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / "Dockerfile").exists()
        # No LLM files
        assert not (path / "mind.py").exists()
        assert not (path / "CLAUDE.md").exists()
        # Compiles
        py_compile.compile(str(path / "agent.py"), doraise=True)
        # Config correct
        yaml_content = (path / "agent.yaml").read_text()
        assert "AGORA_MOD_TOKEN" in yaml_content
        assert "respond_mode: all" in yaml_content
        assert "mod-log: write-only" in yaml_content

    def test_init_bare_produces_minimal_dir(self, tmp_path):
        path = init_agent("custom", path=tmp_path / "custom", template="bare")
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert not (path / "Dockerfile").exists()
        assert not (path / "mind.py").exists()
        py_compile.compile(str(path / "agent.py"), doraise=True)

    def test_each_agent_gets_unique_token_env(self, tmp_path):
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        init_agent("rex", path=tmp_path / "rex", template="citizen")
        init_agent("mod", path=tmp_path / "mod", template="moderator")

        nova_yaml = (tmp_path / "nova" / "agent.yaml").read_text()
        rex_yaml = (tmp_path / "rex" / "agent.yaml").read_text()
        mod_yaml = (tmp_path / "mod" / "agent.yaml").read_text()

        assert "AGORA_NOVA_TOKEN" in nova_yaml
        assert "AGORA_REX_TOKEN" in rex_yaml
        assert "AGORA_MOD_TOKEN" in mod_yaml

    def test_moderator_dockerfile_no_claude_cli(self, tmp_path):
        """Moderator Dockerfile should NOT install Claude CLI."""
        path = init_agent("mod", path=tmp_path / "mod", template="moderator")
        dockerfile = (path / "Dockerfile").read_text()
        assert "claude" not in dockerfile.lower() or "claude-code" not in dockerfile
        assert "nodejs" not in dockerfile.lower()

    def test_citizen_dockerfile_has_claude_cli(self, tmp_path):
        """Citizen Dockerfile should install Claude CLI."""
        path = init_agent("nova", path=tmp_path / "nova", template="citizen")
        dockerfile = (path / "Dockerfile").read_text()
        assert "claude-code" in dockerfile

    def test_citizen_dockerfile_uses_fleet_path(self, tmp_path):
        """Citizen Dockerfile should COPY from fleet/<name>/."""
        path = init_agent("nova", path=tmp_path / "nova", template="citizen")
        dockerfile = (path / "Dockerfile").read_text()
        assert "COPY fleet/nova/" in dockerfile
        assert "COPY agora/" in dockerfile
        assert "COPY pyproject.toml" in dockerfile

    def test_init_collision_raises(self, tmp_path):
        """Re-init to same path raises FileExistsError."""
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        with pytest.raises(FileExistsError, match="already exists"):
            init_agent("nova", path=tmp_path / "nova", template="citizen")


class TestComposeServiceBlock:
    """Test compose_service_block() codegen."""

    def test_generates_service_dict(self, tmp_path):
        agent_dir = tmp_path / "fleet" / "rex"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text("name: rex\ntoken_env: AGORA_REX_TOKEN\n")
        (agent_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")

        block = compose_service_block(agent_dir)
        assert "rex" in block
        svc = block["rex"]
        assert svc["container_name"] == "agora-rex"
        assert svc["restart"] == "unless-stopped"
        assert svc["build"]["context"] == "."
        assert "Dockerfile" in svc["build"]["dockerfile"]

    def test_missing_agent_yaml_raises(self, tmp_path):
        agent_dir = tmp_path / "fleet" / "ghost"
        agent_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="No agent.yaml"):
            compose_service_block(agent_dir)

    def test_uses_dir_name_if_no_name_in_yaml(self, tmp_path):
        agent_dir = tmp_path / "fleet" / "fallback"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text("token_env: AGORA_TOKEN\n")
        block = compose_service_block(agent_dir)
        assert "fallback" in block


class TestScanFleet:
    """Test _scan_fleet() directory scanning."""

    def test_scans_fleet_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fleet_dir = tmp_path / "fleet"
        fleet_dir.mkdir()
        for name in ("nova", "rex"):
            d = fleet_dir / name
            d.mkdir()
            (d / "agent.yaml").write_text(f"name: {name}\n")
        # Directory without agent.yaml should be skipped
        (fleet_dir / "junk").mkdir()

        agents = _scan_fleet()
        assert len(agents) == 2
        names = [a.name for a in agents]
        assert "nova" in names
        assert "rex" in names

    def test_no_fleet_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _scan_fleet() == []


class TestEnsureCompose:
    """Test _ensure_compose() generation."""

    def test_creates_compose_from_fleet(self, tmp_path, monkeypatch):
        import yaml
        monkeypatch.chdir(tmp_path)
        fleet_dir = tmp_path / "fleet"
        fleet_dir.mkdir()
        for name in ("nova", "rex"):
            d = fleet_dir / name
            d.mkdir()
            (d / "agent.yaml").write_text(f"name: {name}\n")
            (d / "Dockerfile").write_text("FROM python:3.12-slim\n")

        compose_path = _ensure_compose()
        assert compose_path.exists()
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        assert "nova" in compose["services"]
        assert "rex" in compose["services"]

    def test_preserves_existing_compose(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        compose_path = tmp_path / "docker-compose.yml"
        compose_path.write_text("services:\n  existing: {}\n")
        result = _ensure_compose()
        assert result == compose_path
        assert "existing" in result.read_text()


class TestFleetCommands:
    """Fleet commands use docker compose. Mock subprocess for unit tests."""

    def _setup_fleet(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fleet_dir = tmp_path / "fleet"
        fleet_dir.mkdir()
        for name in ("nova", "rex"):
            d = fleet_dir / name
            d.mkdir()
            (d / "agent.yaml").write_text(f"name: {name}\n")
            (d / "Dockerfile").write_text("FROM python:3.12-slim\n")
            (d / ".env").write_text(f"TOKEN=test\n")

    def test_fleet_start_no_runtime(self, tmp_path, capsys, monkeypatch):
        self._setup_fleet(tmp_path, monkeypatch)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        failures = fleet_start()
        assert failures == 1

    def test_fleet_start_no_agents(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "docker")
        failures = fleet_start()
        out = capsys.readouterr().out
        assert "No agents in fleet/" in out
        assert failures == 0

    def test_fleet_stop_no_runtime(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        failures = fleet_stop()
        assert failures == 1

    def test_fleet_status_no_runtime(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        fleet_status()
        out = capsys.readouterr().out
        assert "No container runtime" in out

    def test_fleet_start_warns_missing_env(self, tmp_path, capsys, monkeypatch):
        """Fleet start warns when .env is missing but doesn't block."""
        monkeypatch.chdir(tmp_path)
        fleet_dir = tmp_path / "fleet" / "nova"
        fleet_dir.mkdir(parents=True)
        (fleet_dir / "agent.yaml").write_text("name: nova\n")
        (fleet_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")
        # No .env file

        import subprocess
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "docker")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )
        fleet_start()
        out = capsys.readouterr().out
        assert "Warning" in out
        assert ".env" in out
