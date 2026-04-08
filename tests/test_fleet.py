"""Tests for fleet management — multi-agent init, registry, and fleet commands.

These tests validate the full fleet workflow: initializing multiple agents
from different templates, checking registry state, and running fleet commands.
No actual containers are started — container operations are mocked.
"""

from __future__ import annotations

import json
import py_compile

import pytest

from agora.cli import init_agent, fleet_start, fleet_stop, fleet_status


@pytest.fixture(autouse=True)
def isolate_registry(tmp_path, monkeypatch):
    """Prevent tests from polluting the real ~/.agora/registry.json."""
    reg_dir = tmp_path / "dot-agora"
    reg_dir.mkdir()
    monkeypatch.setattr("agora.registry.REGISTRY_DIR", reg_dir)
    monkeypatch.setattr("agora.registry.REGISTRY_PATH", reg_dir / "registry.json")


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

    def test_init_three_agents_registers_all(self, tmp_path):
        """Simulate the testbed fleet: 2 citizens + 1 moderator."""
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        init_agent("rex", path=tmp_path / "rex", template="citizen")
        init_agent("mod", path=tmp_path / "mod", template="moderator")

        from agora.registry import load_registry
        reg = load_registry()
        citizens = reg["citizens"]

        assert "nova" in citizens
        assert "rex" in citizens
        assert "mod" in citizens

        # Check roles
        assert citizens["nova"]["role"] == "citizen"
        assert citizens["rex"]["role"] == "citizen"
        assert citizens["mod"]["role"] == "moderator"

        # Check display names
        assert citizens["nova"]["display_name"] == "Nova"
        assert citizens["rex"]["display_name"] == "Rex"
        assert citizens["mod"]["display_name"] == "Mod"

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


class TestFleetWithMultipleAgents:
    """Test fleet commands operating on a multi-agent registry."""

    def _setup_fleet(self, tmp_path):
        """Initialize a 3-agent fleet."""
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        init_agent("rex", path=tmp_path / "rex", template="citizen")
        init_agent("mod", path=tmp_path / "mod", template="moderator")

    def test_fleet_status_all_agents(self, tmp_path, capsys, monkeypatch):
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        fleet_status()
        out = capsys.readouterr().out
        assert "nova" in out
        assert "rex" in out
        assert "mod" in out
        assert "citizen" in out
        assert "moderator" in out

    def test_fleet_status_filter_citizens_only(self, tmp_path, capsys, monkeypatch):
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        fleet_status(role="citizen")
        out = capsys.readouterr().out
        assert "nova" in out
        assert "rex" in out
        assert "mod" not in out

    def test_fleet_status_filter_moderator_only(self, tmp_path, capsys, monkeypatch):
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        fleet_status(role="moderator")
        out = capsys.readouterr().out
        assert "mod" in out
        assert "nova" not in out
        assert "rex" not in out

    def test_fleet_start_with_no_runtime(self, tmp_path, capsys, monkeypatch):
        """Fleet start should report failure if no container runtime."""
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        monkeypatch.setattr("agora.cli._is_container_running", lambda r, n: False)
        failures = fleet_start()
        out = capsys.readouterr().out
        # All 3 agents should fail (no runtime)
        assert failures == 3

    def test_fleet_start_already_running(self, tmp_path, capsys, monkeypatch):
        """Fleet start reports already-running containers without error."""
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "podman")
        monkeypatch.setattr("agora.cli._is_container_running", lambda r, n: True)
        failures = fleet_start()
        out = capsys.readouterr().out
        assert "already running" in out
        assert failures == 0

    def test_fleet_stop_nothing_running(self, tmp_path, capsys, monkeypatch):
        """Fleet stop with no running containers is a no-op."""
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "podman")
        monkeypatch.setattr("agora.cli._is_container_running", lambda r, n: False)
        failures = fleet_stop()
        out = capsys.readouterr().out
        assert "not running" in out
        assert failures == 0

    def test_fleet_stop_role_filter(self, tmp_path, capsys, monkeypatch):
        """fleet stop --role moderator should only stop the moderator."""
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "podman")
        # Only mod is running
        monkeypatch.setattr("agora.cli._is_container_running",
                            lambda r, n: n == "agora-mod")
        import subprocess
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )
        failures = fleet_stop(role="moderator")
        out = capsys.readouterr().out
        assert "mod" in out
        assert "nova" not in out

    def test_mixed_fleet_with_non_container(self, tmp_path, capsys, monkeypatch):
        """Fleet with echo (non-container) and citizen (container) agents."""
        init_agent("echo-bot", path=tmp_path / "echo-bot", template="echo")
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: "podman")
        monkeypatch.setattr("agora.cli._is_container_running", lambda r, n: True)
        failures = fleet_start()
        out = capsys.readouterr().out
        assert "non-container" in out  # echo skipped
        assert "already running" in out  # nova detected
        assert failures == 0

    def test_fleet_status_display_names_and_roles(self, tmp_path, capsys, monkeypatch):
        """Verify fleet status shows enriched registry fields."""
        self._setup_fleet(tmp_path)
        monkeypatch.setattr("agora.cli._detect_runtime", lambda: None)
        fleet_status()
        out = capsys.readouterr().out
        # Header
        assert "NAME" in out
        assert "DISPLAY" in out
        assert "ROLE" in out
        assert "STATUS" in out
        # Data
        assert "Nova" in out
        assert "Rex" in out
        assert "Mod" in out


class TestRegistryEnrichment:
    """Test that init populates display_name and role in registry."""

    def test_citizen_gets_citizen_role(self, tmp_path):
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        from agora.registry import load_registry
        entry = load_registry()["citizens"]["nova"]
        assert entry["role"] == "citizen"
        assert entry["display_name"] == "Nova"
        assert entry["template"] == "citizen"

    def test_moderator_gets_moderator_role(self, tmp_path):
        init_agent("mod", path=tmp_path / "mod", template="moderator")
        from agora.registry import load_registry
        entry = load_registry()["citizens"]["mod"]
        assert entry["role"] == "moderator"
        assert entry["display_name"] == "Mod"

    def test_bare_gets_bare_role(self, tmp_path):
        init_agent("custom", path=tmp_path / "custom", template="bare")
        from agora.registry import load_registry
        entry = load_registry()["citizens"]["custom"]
        assert entry["role"] == "bare"

    def test_echo_gets_echo_role(self, tmp_path):
        init_agent("ping", path=tmp_path / "ping", template="echo")
        from agora.registry import load_registry
        entry = load_registry()["citizens"]["ping"]
        assert entry["role"] == "echo"

    def test_hyphenated_name_display(self, tmp_path):
        init_agent("my-cool-bot", path=tmp_path / "my-cool-bot", template="bare")
        from agora.registry import load_registry
        entry = load_registry()["citizens"]["my-cool-bot"]
        assert entry["display_name"] == "My Cool Bot"

    def test_registry_json_structure(self, tmp_path):
        """Verify the registry JSON has correct structure after multi-agent init."""
        init_agent("nova", path=tmp_path / "nova", template="citizen")
        init_agent("mod", path=tmp_path / "mod", template="moderator")

        from agora.registry import REGISTRY_PATH
        raw = json.loads(REGISTRY_PATH.read_text())
        assert "citizens" in raw
        assert len(raw["citizens"]) == 2

        nova = raw["citizens"]["nova"]
        assert set(nova.keys()) == {"path", "template", "created", "display_name", "role"}
