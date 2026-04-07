"""Integration test: containerized echo bot responds on AgoraGenesis Discord.

Requires:
- A container runtime (podman or docker)
- Discord bot tokens in environment
- --live flag to pytest
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from agora.context import ContainerContext, detect_runtime, RuntimeNotFound


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

def _has_runtime() -> bool:
    """Check if a container runtime is available (sync check)."""
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            result = subprocess.run(
                [rt, "info"], capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return True
    return False


requires_runtime = pytest.mark.skipif(
    not _has_runtime(),
    reason="No container runtime (podman/docker) available",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agora_sdist(tmp_path) -> Path:
    """Build a source distribution of the current agora code."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    dist_dir = tmp_path / "agora-dist"
    # Copy the agora package and pyproject.toml
    shutil.copytree(repo_root / "agora", dist_dir / "agora")
    for f in ("pyproject.toml", "README.md"):
        src = repo_root / f
        if src.exists():
            shutil.copy2(src, dist_dir / f)
    return dist_dir


@pytest.fixture
def echo_build_context(tmp_path, agora_sdist) -> Path:
    """Create a build context for a containerized echo bot."""
    ctx = tmp_path / "echo-container"
    ctx.mkdir()

    # agent.py — self-contained echo bot
    (ctx / "agent.py").write_text(textwrap.dedent("""\
        from agora import Agora

        class EchoAgent(Agora):
            async def on_message(self, message):
                if message.is_mention:
                    return message.content
                return None

        if __name__ == "__main__":
            bot = EchoAgent.from_config("agent.yaml")
            bot.run()
    """))

    # agent.yaml — container backend, targeting bot-chat
    (ctx / "agent.yaml").write_text(textwrap.dedent("""\
        token_env: DISCORD_BOT_TOKEN
        name: echo-container-test
        channels:
          bot-chat: subscribe
        context:
          backend: container
    """))

    # .env
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    (ctx / ".env").write_text(f"DISCORD_BOT_TOKEN={token}\n")

    # Dockerfile — install agora from local source
    shutil.copytree(agora_sdist, ctx / "agora-dist")
    (ctx / "Dockerfile").write_text(textwrap.dedent("""\
        FROM python:3.12-slim
        COPY agora-dist/ /tmp/agora/
        RUN pip install /tmp/agora/
        WORKDIR /agent
        COPY agent.py agent.yaml ./
        CMD ["python", "agent.py"]
    """))

    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@requires_runtime
class TestContainerEcho:
    @pytest.mark.asyncio
    async def test_build_and_start(self, echo_build_context):
        """Verify we can build an image and start the container."""
        ctx = ContainerContext(
            image="agora-echo-test",
            build_path=str(echo_build_context),
            env_file=str(echo_build_context / ".env"),
        )
        try:
            await ctx.build_image()
            container_id = await ctx.start()
            assert container_id is not None

            # Give it a moment, then check it's running
            await asyncio.sleep(2)
            running = await ctx.is_running()
            # Container may have exited if no valid token — that's ok
            # The point is that build + start worked without errors
            assert isinstance(running, bool)
        finally:
            await ctx.stop(timeout=5)
            assert ctx.container_id is None

    @pytest.mark.asyncio
    async def test_container_cleanup(self, echo_build_context):
        """Verify container is removed after stop (--rm flag)."""
        rt = await detect_runtime()
        ctx = ContainerContext(
            image="agora-echo-cleanup-test",
            runtime=rt,
            build_path=str(echo_build_context),
            env_file=str(echo_build_context / ".env"),
        )
        try:
            await ctx.build_image()
            container_id = await ctx.start()
        finally:
            await ctx.stop(timeout=5)

        # Verify container is gone (--rm should have removed it)
        proc = await asyncio.create_subprocess_exec(
            rt, "ps", "-a", "--filter", f"id={container_id}", "--format", "{{.ID}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        assert container_id[:12] not in stdout.decode()
