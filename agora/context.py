"""Pluggable execution contexts for Agora agents."""

from __future__ import annotations

import asyncio
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ExecResult:
    """Result of running a command in an execution context."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class ContextError(Exception):
    """Base error for execution context failures."""


class RuntimeNotFound(ContextError):
    """Container runtime (Docker/Podman) is not installed or not reachable."""


class ImageBuildError(ContextError):
    """Failed to build a container image."""


class ContainerCrashed(ContextError):
    """Container exited unexpectedly (OOM, killed, etc.)."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ExecutionContext(ABC):
    """Where an agent runs — local process or container."""

    @abstractmethod
    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        """Run *command* and return the result."""

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """Read a text file relative to working_dir()."""

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """Write a text file relative to working_dir()."""

    @abstractmethod
    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries relative to working_dir()."""

    @abstractmethod
    def working_dir(self) -> str:
        """Absolute path to the context's working directory."""


# ---------------------------------------------------------------------------
# Local implementation
# ---------------------------------------------------------------------------

class LocalContext(ExecutionContext):
    """Default context — agent runs as a normal process on the host."""

    def __init__(self, working_dir: str = ".") -> None:
        self._working_dir = str(Path(working_dir).resolve())

    def working_dir(self) -> str:
        return self._working_dir

    def _resolve(self, path: str) -> Path:
        """Resolve *path* relative to working_dir (unless already absolute)."""
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(self._working_dir) / p

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        run_cwd = self._resolve(cwd) if cwd else self._working_dir
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(run_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            timed_out = True

        return ExecResult(
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
            timed_out=timed_out,
        )

    async def read_file(self, path: str) -> str:
        return self._resolve(path).read_text()

    async def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    async def list_dir(self, path: str = ".") -> list[str]:
        return sorted(p.name for p in self._resolve(path).iterdir())


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------

_RUNTIMES = ("podman", "docker")


async def detect_runtime() -> str:
    """Find a working container runtime.

    Checks ``AGORA_RUNTIME`` env var first, then tries podman → docker.
    A runtime is considered "working" only if ``<runtime> info`` succeeds.
    Raises :class:`RuntimeNotFound` if nothing works.
    """
    env = os.environ.get("AGORA_RUNTIME")
    candidates = (env,) if env else _RUNTIMES

    for name in candidates:
        if not shutil.which(name):
            continue
        proc = await asyncio.create_subprocess_exec(
            name, "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            continue
        if rc == 0:
            return name

    if env:
        raise RuntimeNotFound(
            f"AGORA_RUNTIME={env!r} is set but '{env} info' failed. "
            f"Is {env} installed and running?"
        )
    raise RuntimeNotFound(
        "No container runtime found. Install podman or docker, then retry."
    )


# ---------------------------------------------------------------------------
# Container lifecycle manager (host-side)
# ---------------------------------------------------------------------------

class ContainerContext:
    """Manages the lifecycle of a containerised agent from the host.

    This is NOT an :class:`ExecutionContext` — it does not implement
    exec/read_file/write_file.  Inside the container the agent uses
    :class:`LocalContext`.  This class handles build → start → stop
    from the host side.
    """

    def __init__(
        self,
        image: str,
        runtime: str | None = None,
        env_file: str = ".env",
        mounts: list[str] | None = None,
        build_path: str = ".",
    ) -> None:
        self.image = image
        self._runtime: str | None = runtime  # resolved lazily
        self.env_file = env_file
        self.mounts = mounts or []
        self.build_path = build_path
        self._container_id: str | None = None

    # -- runtime resolution --------------------------------------------------

    async def runtime(self) -> str:
        """Return the container runtime, detecting if necessary."""
        if self._runtime is None:
            self._runtime = await detect_runtime()
        return self._runtime

    # -- image ---------------------------------------------------------------

    async def build_image(self, *, no_cache: bool = False) -> None:
        """Build the container image from *build_path*."""
        rt = await self.runtime()
        cmd = [rt, "build", "-t", self.image]
        if no_cache:
            cmd.append("--no-cache")
        cmd.append(self.build_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ImageBuildError(
                f"Image build failed (exit {proc.returncode}):\n"
                + stderr.decode(errors="replace")
            )

    # -- container lifecycle -------------------------------------------------

    async def start(self, name: str | None = None) -> str:
        """Start the container in detached mode.  Returns the container ID."""
        rt = await self.runtime()
        cmd = [rt, "run", "-d", "--rm"]

        if name:
            cmd.extend(["--name", name])

        env_path = Path(self.env_file) if Path(self.env_file).is_absolute() else Path(self.build_path) / self.env_file
        if env_path.exists():
            cmd.extend(["--env-file", str(env_path.resolve())])

        for mount in self.mounts:
            cmd.extend(["-v", mount])

        cmd.append(self.image)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ContextError(
                f"Failed to start container (exit {proc.returncode}):\n"
                + stderr.decode(errors="replace")
            )

        self._container_id = stdout.decode().strip()
        return self._container_id

    async def stop(self, timeout: int = 10) -> None:
        """Gracefully stop the container."""
        if not self._container_id:
            return
        rt = await self.runtime()

        proc = await asyncio.create_subprocess_exec(
            rt, "stop", "-t", str(timeout), self._container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        self._container_id = None

    async def is_running(self) -> bool:
        """Check whether the container is still running."""
        if not self._container_id:
            return False
        rt = await self.runtime()

        proc = await asyncio.create_subprocess_exec(
            rt, "inspect", "--format", "{{.State.Running}}", self._container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip().lower() == "true"

    @property
    def container_id(self) -> str | None:
        return self._container_id
