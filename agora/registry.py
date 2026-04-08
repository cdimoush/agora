"""Citizen registry for fleet management.

Maintains a lightweight JSON registry at ~/.agora/registry.json.
Auto-populated by agora init and agora run. Used by agora status and agora stop.
"""

from __future__ import annotations

import fcntl
import json
from datetime import date
from pathlib import Path

REGISTRY_DIR = Path.home() / ".agora"
REGISTRY_PATH = REGISTRY_DIR / "registry.json"


def _ensure_dir() -> None:
    """Create ~/.agora/ if it doesn't exist."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


def load_registry() -> dict:
    """Load the registry. Returns empty structure if missing."""
    if not REGISTRY_PATH.exists():
        return {"citizens": {}}
    try:
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
        if "citizens" not in data:
            data["citizens"] = {}
        return data
    except (json.JSONDecodeError, OSError):
        return {"citizens": {}}


def _save_registry(data: dict) -> None:
    """Save the registry with file locking."""
    _ensure_dir()
    with open(REGISTRY_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
            f.write("\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def register(
    name: str,
    path: str,
    template: str = "unknown",
    created: str | None = None,
) -> None:
    """Register a citizen. Errors if name is registered to a different path."""
    _ensure_dir()

    # Lock and read-modify-write
    with open(REGISTRY_PATH, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            if content.strip():
                data = json.loads(content)
            else:
                data = {"citizens": {}}

            if "citizens" not in data:
                data["citizens"] = {}

            existing = data["citizens"].get(name)
            if existing and existing.get("path") != path:
                raise ValueError(
                    f"Agent '{name}' is already registered at {existing['path']}. "
                    f"Use a different name or remove the existing citizen."
                )

            data["citizens"][name] = {
                "path": path,
                "template": template,
                "created": created or date.today().isoformat(),
            }

            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
            f.write("\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
