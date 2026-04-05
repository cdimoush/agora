"""Start the full Agora testbed — moderator + two citizens.

Usage:
    python testbed/run.py

Runs until Ctrl+C. Requires .env files in each bot subdirectory.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))


def _import_from_path(module_name: str, file_path: Path):
    """Import a module from a file path (handles hyphenated directory names)."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


testbed_dir = repo_root / "testbed"
_mod_module = _import_from_path("mod", testbed_dir / "moderator" / "mod.py")
_citizen_a_module = _import_from_path("citizen_a", testbed_dir / "citizen-a" / "citizen.py")
_citizen_b_module = _import_from_path("citizen_b", testbed_dir / "citizen-b" / "citizen.py")

ModeratorBot = _mod_module.ModeratorBot
CitizenA = _citizen_a_module.CitizenBot
CitizenB = _citizen_b_module.CitizenBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("testbed")


def _load_env(path: Path) -> None:
    """Source a .env file into os.environ."""
    if not path.exists():
        logger.warning("No .env at %s — skipping", path)
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()


async def main():
    # Load .env files for each bot
    _load_env(testbed_dir / "moderator" / ".env")
    _load_env(testbed_dir / "citizen-a" / ".env")
    _load_env(testbed_dir / "citizen-b" / ".env")

    # Create bot instances from their configs
    mod = ModeratorBot.from_config(str(testbed_dir / "moderator" / "agent.yaml"))
    citizen_a = CitizenA.from_config(str(testbed_dir / "citizen-a" / "agent.yaml"))
    citizen_b = CitizenB.from_config(str(testbed_dir / "citizen-b" / "agent.yaml"))

    bots = [mod, citizen_a, citizen_b]

    # Conversation replay (file-based telemetry is auto-enabled via agent.yaml)
    from agora.telemetry import ReplayProcessor

    replay_proc = ReplayProcessor()
    for bot in bots:
        bot.add_processor(replay_proc)

    # Signal handling for graceful shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Start all three bots concurrently
    tasks = [
        asyncio.create_task(bot._client.start(bot.config.token))
        for bot in bots
    ]

    logger.info("Testbed started — moderator + 2 citizens. Ctrl+C to stop.")

    await stop_event.wait()

    logger.info("Shutting down...")

    # Print conversation replay before closing
    replay_output = replay_proc.replay()
    if replay_output:
        print("\n── Conversation Replay ──")
        print(replay_output)
        print("── End Replay ──\n")

    for bot in bots:
        await bot._client.close()
    for task in tasks:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
