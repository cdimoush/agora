"""Pluggable execution contexts for Agora agents."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
