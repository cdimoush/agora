"""Tests for agora.context — ExecutionContext, LocalContext, ContainerContext."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path, monkeypatch):
    """Prevent tests from polluting the real ~/.agora/registry.json."""
    reg_dir = tmp_path / "dot-agora"
    reg_dir.mkdir()
    monkeypatch.setattr("agora.registry.REGISTRY_DIR", reg_dir)
    monkeypatch.setattr("agora.registry.REGISTRY_PATH", reg_dir / "registry.json")


from agora.context import (
    ContainerContext,
    ContainerCrashed,
    ContextError,
    ExecResult,
    ExecutionContext,
    ImageBuildError,
    LocalContext,
    RuntimeNotFound,
    detect_runtime,
)


# ---------------------------------------------------------------------------
# ExecResult
# ---------------------------------------------------------------------------

class TestExecResult:
    def test_defaults(self):
        r = ExecResult(stdout="ok", stderr="", exit_code=0)
        assert r.timed_out is False

    def test_all_fields(self):
        r = ExecResult(stdout="out", stderr="err", exit_code=42, timed_out=True)
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.exit_code == 42
        assert r.timed_out is True


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class TestErrorHierarchy:
    def test_runtime_not_found_is_context_error(self):
        assert issubclass(RuntimeNotFound, ContextError)

    def test_image_build_error_is_context_error(self):
        assert issubclass(ImageBuildError, ContextError)

    def test_container_crashed_is_context_error(self):
        assert issubclass(ContainerCrashed, ContextError)

    def test_can_catch_as_context_error(self):
        with pytest.raises(ContextError):
            raise RuntimeNotFound("no runtime")


# ---------------------------------------------------------------------------
# LocalContext
# ---------------------------------------------------------------------------

class TestLocalContext:
    @pytest.mark.asyncio
    async def test_exec_echo(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        result = await ctx.exec("echo hello")
        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_exec_stderr(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        result = await ctx.exec("echo err >&2")
        assert result.stderr == "err\n"

    @pytest.mark.asyncio
    async def test_exec_failure(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        result = await ctx.exec("false")
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_exec_timeout(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        result = await ctx.exec("sleep 10", timeout=0.3)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_exec_cwd(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        ctx = LocalContext(str(tmp_path))
        result = await ctx.exec("pwd", cwd="sub")
        assert result.stdout.strip() == str(sub)

    @pytest.mark.asyncio
    async def test_read_write_file(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        await ctx.write_file("test.txt", "hello world")
        content = await ctx.read_file("test.txt")
        assert content == "hello world"

    @pytest.mark.asyncio
    async def test_write_file_creates_parents(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        await ctx.write_file("a/b/c.txt", "deep")
        content = await ctx.read_file("a/b/c.txt")
        assert content == "deep"

    @pytest.mark.asyncio
    async def test_list_dir(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        ctx = LocalContext(str(tmp_path))
        entries = await ctx.list_dir()
        assert "a.txt" in entries
        assert "b.txt" in entries

    def test_working_dir_absolute(self, tmp_path):
        ctx = LocalContext(str(tmp_path))
        wd = ctx.working_dir()
        assert Path(wd).is_absolute()
        assert wd == str(tmp_path)

    @pytest.mark.asyncio
    async def test_absolute_path(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        (other / "file.txt").write_text("absolute")
        ctx = LocalContext(str(tmp_path))
        content = await ctx.read_file(str(other / "file.txt"))
        assert content == "absolute"


# ---------------------------------------------------------------------------
# detect_runtime (mocked)
# ---------------------------------------------------------------------------

class TestDetectRuntime:
    @pytest.mark.asyncio
    async def test_finds_podman(self):
        async def fake_exec(*args, **kwargs):
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("shutil.which", return_value="/usr/bin/podman"), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await detect_runtime()
            assert result == "podman"

    @pytest.mark.asyncio
    async def test_falls_back_to_docker(self):
        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            proc = MagicMock()
            call_count += 1
            # podman fails, docker succeeds
            proc.wait = AsyncMock(return_value=1 if call_count == 1 else 0)
            return proc

        def which(name):
            return f"/usr/bin/{name}"

        with patch("shutil.which", side_effect=which), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await detect_runtime()
            assert result == "docker"

    @pytest.mark.asyncio
    async def test_raises_when_none_found(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeNotFound):
                await detect_runtime()

    @pytest.mark.asyncio
    async def test_respects_agora_runtime_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_RUNTIME", "docker")

        async def fake_exec(*args, **kwargs):
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await detect_runtime()
            assert result == "docker"

    @pytest.mark.asyncio
    async def test_agora_runtime_env_not_installed(self, monkeypatch):
        monkeypatch.setenv("AGORA_RUNTIME", "podman")
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeNotFound, match="AGORA_RUNTIME"):
                await detect_runtime()


# ---------------------------------------------------------------------------
# ContainerContext (mocked)
# ---------------------------------------------------------------------------

class TestContainerContext:
    @pytest.mark.asyncio
    async def test_build_image_calls_runtime(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await ctx.build_image()
            args = mock_exec.call_args[0]
            assert args[0] == "podman"
            assert "build" in args
            assert "-t" in args
            assert "test-img" in args

    @pytest.mark.asyncio
    async def test_build_image_no_cache(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await ctx.build_image(no_cache=True)
            args = mock_exec.call_args[0]
            assert "--no-cache" in args

    @pytest.mark.asyncio
    async def test_build_image_failure(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"build error details"))
        proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(ImageBuildError, match="build error details"):
                await ctx.build_image()

    @pytest.mark.asyncio
    async def test_start_returns_container_id(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TOKEN=x")
        ctx = ContainerContext(image="test-img", runtime="podman", env_file=str(env_file))
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            cid = await ctx.start()
            assert cid == "abc123"
            assert ctx.container_id == "abc123"

    @pytest.mark.asyncio
    async def test_start_with_mounts(self):
        ctx = ContainerContext(
            image="test-img", runtime="podman",
            mounts=["/host/path:/container/path"],
        )
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await ctx.start()
            args = mock_exec.call_args[0]
            assert "-v" in args
            assert "/host/path:/container/path" in args

    @pytest.mark.asyncio
    async def test_stop(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        ctx._container_id = "abc123"
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await ctx.stop()
            args = mock_exec.call_args[0]
            assert "stop" in args
            assert "abc123" in args
            assert ctx.container_id is None

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_running(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        await ctx.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_is_running_true(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        ctx._container_id = "abc123"
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"true\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            assert await ctx.is_running() is True

    @pytest.mark.asyncio
    async def test_is_running_false_no_id(self):
        ctx = ContainerContext(image="test-img", runtime="podman")
        assert await ctx.is_running() is False

    @pytest.mark.asyncio
    async def test_runtime_auto_detects(self):
        ctx = ContainerContext(image="test-img")

        async def fake_detect():
            return "docker"

        with patch("agora.context.detect_runtime", side_effect=fake_detect):
            rt = await ctx.runtime()
            assert rt == "docker"


# ---------------------------------------------------------------------------
# Config context parsing
# ---------------------------------------------------------------------------

class TestConfigContextParsing:
    def test_no_context_section(self, tmp_path):
        from agora.config import Config
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text("token_env: TEST_TOKEN\nchannels:\n  general: mention-only\n")
        cfg = Config.from_yaml(cfg_file)
        assert cfg.context_backend is None
        assert cfg.context_runtime is None
        assert cfg.context_image is None

    def test_container_backend(self, tmp_path):
        from agora.config import Config
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text(
            "token_env: TEST_TOKEN\nchannels:\n  general: mention-only\n"
            "context:\n  backend: container\n"
        )
        cfg = Config.from_yaml(cfg_file)
        assert cfg.context_backend == "container"

    def test_runtime_and_image(self, tmp_path):
        from agora.config import Config
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text(
            "token_env: TEST_TOKEN\nchannels:\n  general: mention-only\n"
            "context:\n  backend: container\n  runtime: docker\n  image: my-agent\n"
        )
        cfg = Config.from_yaml(cfg_file)
        assert cfg.context_runtime == "docker"
        assert cfg.context_image == "my-agent"

    def test_invalid_backend(self, tmp_path):
        from agora.config import Config, ConfigError
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text(
            "token_env: TEST_TOKEN\nchannels:\n  general: mention-only\n"
            "context:\n  backend: invalid\n"
        )
        with pytest.raises(ConfigError, match="context.backend"):
            Config.from_yaml(cfg_file)

    def test_invalid_runtime(self, tmp_path):
        from agora.config import Config, ConfigError
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text(
            "token_env: TEST_TOKEN\nchannels:\n  general: mention-only\n"
            "context:\n  backend: container\n  runtime: rkt\n"
        )
        with pytest.raises(ConfigError, match="context.runtime"):
            Config.from_yaml(cfg_file)


# ---------------------------------------------------------------------------
# CLI scaffolding — container mode
# ---------------------------------------------------------------------------

class TestInitContainer:
    def test_container_generates_all_files(self, tmp_path):
        from agora.cli import init_agent
        path = init_agent("box-test", path=tmp_path / "box-test")
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert (path / "Dockerfile").exists()
        assert (path / ".env.example").exists()
        assert (path / ".gitignore").exists()

    def test_container_yaml_has_context(self, tmp_path):
        from agora.cli import init_agent
        from agora.config import Config
        path = init_agent("ctx-test", path=tmp_path / "ctx-test")
        cfg = Config.from_yaml(path / "agent.yaml")
        assert cfg.context_backend == "container"

    def test_gitignore_contains_env(self, tmp_path):
        from agora.cli import init_agent
        path = init_agent("gi-test", path=tmp_path / "gi-test")
        gitignore = (path / ".gitignore").read_text()
        assert ".env" in gitignore

    def test_dockerfile_has_from(self, tmp_path):
        from agora.cli import init_agent
        path = init_agent("df-test", path=tmp_path / "df-test")
        dockerfile = (path / "Dockerfile").read_text()
        assert "FROM python:3.12-slim" in dockerfile

    def test_echo_template(self, tmp_path):
        from agora.cli import init_agent
        path = init_agent("local-test", path=tmp_path / "local-test", template="echo")
        assert (path / "agent.py").exists()
        assert (path / "agent.yaml").exists()
        assert not (path / "Dockerfile").exists()
        assert not (path / ".env.example").exists()


# ---------------------------------------------------------------------------
# Config validation — unknown keys
# ---------------------------------------------------------------------------

class TestConfigValidation:
    """Tests for Config.from_yaml unknown key rejection."""

    def test_unknown_key_raises_config_error(self, tmp_path):
        from agora.config import Config, ConfigError
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text("token_env: MY_TOKEN\ntypo_field: oops\n")
        with pytest.raises(ConfigError, match="Unknown config key.*typo_field"):
            Config.from_yaml(cfg_file)

    def test_multiple_unknown_keys_listed(self, tmp_path):
        from agora.config import Config, ConfigError
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text("token_env: MY_TOKEN\nbad1: x\nbad2: y\n")
        with pytest.raises(ConfigError, match="bad1.*bad2|bad2.*bad1"):
            Config.from_yaml(cfg_file)


# ---------------------------------------------------------------------------
# detect_runtime timeout
# ---------------------------------------------------------------------------

class TestDetectRuntimeTimeout:
    """Tests for detect_runtime timeout handling."""

    @pytest.mark.asyncio
    async def test_detect_runtime_skips_hanging_runtime(self):
        """A runtime whose 'info' hangs should be skipped, not block forever."""
        hung = AsyncMock()
        hung.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        hung.kill = MagicMock()

        ok_proc = AsyncMock()
        ok_proc.wait = AsyncMock(return_value=0)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return hung  # first candidate hangs
            return ok_proc  # second succeeds

        with patch("shutil.which", return_value="/usr/bin/fake"), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("asyncio.wait_for", side_effect=[asyncio.TimeoutError, 0]):
            from agora.context import detect_runtime, _RUNTIMES
            # Reset to test both candidates
            rt = await detect_runtime()
            assert rt in _RUNTIMES


# ---------------------------------------------------------------------------
# ContainerContext env_file resolution
# ---------------------------------------------------------------------------

class TestContainerEnvFileResolution:
    """Tests that env_file is resolved relative to build_path."""

    @pytest.mark.asyncio
    async def test_env_file_resolved_relative_to_build_path(self, tmp_path):
        """env_file should be found relative to build_path, not CWD."""
        build_dir = tmp_path / "my-agent"
        build_dir.mkdir()
        (build_dir / ".env").write_text("DISCORD_BOT_TOKEN=test\n")

        ctx = ContainerContext(
            image="test",
            runtime="docker",
            build_path=str(build_dir),
        )
        # Inspect the start() command construction by mocking subprocess
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await ctx.start()
            # Check that --env-file was passed with the resolved path
            call_args = mock_exec.call_args[0]
            assert "--env-file" in call_args
            env_idx = list(call_args).index("--env-file")
            env_path = call_args[env_idx + 1]
            assert str(build_dir) in env_path
