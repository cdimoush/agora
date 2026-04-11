"""Agora developer agent — Claude Code in a container.

Uses Claude CLI with full dev tooling (git, beads, skills).
Dual-mode: DM (dev tasks) and channel (social citizen).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
import time
from pathlib import Path

from agora import Agora, Message
from agora.errors import ErrorContext
from mind import DevMind

logger = logging.getLogger("agora.dev")

_ERROR_LINES = [
    "hit a snag, give me a sec",
    "something broke — checking logs",
    "ran into an error, investigating",
]


class Dev(Agora):
    """A developer agent who codes via DM and socializes in channels."""

    def __init__(self, config, project_dir: Path | None = None):
        super().__init__(config)
        self._project_dir = project_dir or Path(__file__).resolve().parent
        self._workspace = Path("/workspace/agora")
        self.mind = DevMind(self._project_dir)

    @classmethod
    def from_config(cls, path: str) -> Dev:
        from agora.config import Config

        config = Config.from_yaml(path)
        project_dir = Path(path).resolve().parent
        return cls(config, project_dir=project_dir)

    async def on_message(self, message: Message) -> str | None:
        """Route to dev mode (DM) or social mode (channel)."""
        if message.is_dm:
            return await self._handle_dm(message)
        return await self._handle_channel(message)

    async def _handle_dm(self, message: Message) -> str | None:
        """Dev mode: full Claude CLI with dev tooling."""
        logger.info("DM from %s: %s", message.author_name, message.content[:100])

        journal_entries = self.mind.read_journal()

        # Gather dev context
        git_status = await self._run_cmd("git status --short", cwd=self._workspace)
        git_branch = await self._run_cmd("git branch --show-current", cwd=self._workspace)
        bd_ready = await self._run_cmd("bd ready", cwd=self._workspace)

        prompt = self.mind.build_dev_prompt(
            operator_message=message.content,
            git_branch=git_branch or "unknown",
            git_status=git_status or "(clean)",
            bd_ready=bd_ready or "(no issues ready)",
            journal_entries=journal_entries,
        )

        response = await self._call_claude(prompt, dev_mode=True)

        if response:
            await self._write_journal_entry(
                trigger="dm",
                channel="dm",
                event_summary=f"Operator asked: {message.content[:80]}. I responded: {response[:80]}",
                spoke=True,
            )

        return response

    async def _handle_channel(self, message: Message) -> str | None:
        """Social mode: citizen behavior."""
        logger.info(
            "on_message from %s in #%s", message.author_name, message.channel_name
        )

        history = await self.get_history(message.channel_name, limit=10)
        history_lines = []
        roster = set()
        for msg in reversed(history):
            if msg.id == message.id:
                continue
            history_lines.append(f"{msg.author_name}: {msg.content}")
            roster.add(msg.author_name)
        roster.add(message.author_name)

        journal_entries = self.mind.read_journal()

        prompt = self.mind.build_reactive_prompt(
            author_name=message.author_name,
            message_content=message.content,
            channel_name=message.channel_name,
            history_lines=history_lines,
            roster=roster,
            journal_entries=journal_entries,
        )

        response = await self._call_claude(prompt, dev_mode=False)

        if response:
            await self._write_journal_entry(
                trigger="reactive",
                channel=message.channel_name,
                event_summary=f"In #{message.channel_name}, {message.author_name} said: {message.content[:100]}. I replied: {response[:100]}",
                spoke=True,
            )

        return response

    async def on_schedule(self) -> dict[str, str] | None:
        """Hourly tick: check channels and beads status."""
        channels = self.get_channels()
        channels_history: dict[str, list[str]] = {}

        for channel_name, mode in channels.items():
            if mode == "write-only" or channel_name == "dm":
                continue
            try:
                history = await self.get_history(channel_name, limit=15)
                lines = []
                for msg in reversed(history):
                    lines.append(f"{msg.author_name}: {msg.content}")
                channels_history[channel_name] = lines
            except Exception as e:
                logger.warning("Failed to read #%s: %s", channel_name, e)
                channels_history[channel_name] = []

        journal_entries = self.mind.read_journal()
        bd_ready = await self._run_cmd("bd ready", cwd=self._workspace)

        prompt = self.mind.build_scan_prompt(
            channels_history, journal_entries, bd_ready=bd_ready or ""
        )
        raw = await self._call_claude(prompt, dev_mode=False)

        if not raw:
            return None

        result = self.mind.parse_scan_response(raw)

        if result:
            channel_name = next(iter(result))
            msg_text = result[channel_name]
            await self._write_journal_entry(
                trigger="scheduled",
                channel=channel_name,
                event_summary=f"Watched the server. Spoke in #{channel_name}: {msg_text[:100]}",
                spoke=True,
            )
            return result
        else:
            await self._write_journal_entry(
                trigger="scheduled",
                channel=None,
                event_summary="Watched the server. Chose silence.",
                spoke=False,
            )
            return None

    async def on_error(self, error: Exception, context: ErrorContext) -> str | None:
        """Fail gracefully."""
        logger.error("Dev error [%s]: %s", context.stage, error)
        return random.choice(_ERROR_LINES)

    # -- Claude CLI -------------------------------------------------------

    async def _call_claude(self, prompt: str, dev_mode: bool = False) -> str | None:
        """Call Claude CLI with mode-specific settings."""
        budget = "10.00" if dev_mode else "0.25"
        timeout = 600 if dev_mode else 60
        cwd = str(self._workspace) if dev_mode and self._workspace.exists() else str(self._project_dir)

        self.emit("inference.request",
            backend="claude-cli", model="opus",
            prompt=prompt, dev_mode=dev_mode,
        )

        start = time.monotonic()

        with self.span("llm_call", model="opus", prompt_length=len(prompt), dev_mode=dev_mode) as s:
            s["prompt_preview"] = prompt[:200]

            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            cmd = [
                "claude", "-p", prompt,
                "--output-format", "json",
                "--model", "opus",
                "--max-budget-usd", budget,
                "--dangerously-skip-permissions",
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                await proc.wait()
                elapsed_ms = (time.monotonic() - start) * 1000
                s["decision"] = "error"
                s["error"] = "timeout"
                self.emit("inference.error",
                    backend="claude-cli", error="timeout",
                    duration_ms=round(elapsed_ms, 2),
                )
                logger.warning("Claude subprocess timed out (%ds)", timeout)
                return None

            elapsed_ms = (time.monotonic() - start) * 1000

            if proc.returncode != 0:
                s["decision"] = "error"
                s["error"] = f"exit={proc.returncode}"
                self.emit("inference.error",
                    backend="claude-cli",
                    error=f"exit={proc.returncode}",
                    duration_ms=round(elapsed_ms, 2),
                )
                logger.error("Claude exit=%d stderr=%s", proc.returncode, stderr.decode()[:500])
                return None

            try:
                data = json.loads(stdout.decode())
            except json.JSONDecodeError:
                s["decision"] = "error"
                s["error"] = "json_decode"
                self.emit("inference.error",
                    backend="claude-cli", error="json_decode",
                    duration_ms=round(elapsed_ms, 2),
                )
                logger.error("Failed to parse Claude JSON output")
                return None

            result = data.get("result", "") or None
            if result:
                s["decision"] = "pass"
                s["response_length"] = len(result)
            else:
                s["decision"] = "empty"

            self.emit("inference.response",
                backend="claude-cli",
                model=data.get("model", "opus"),
                response=result or "",
                input_tokens=data.get("input_tokens"),
                output_tokens=data.get("output_tokens"),
                cost_usd=data.get("total_cost_usd"),
                duration_ms=round(elapsed_ms, 2),
            )

            return result

    # -- Helpers -----------------------------------------------------------

    async def _run_cmd(self, cmd: str, cwd: Path | None = None) -> str | None:
        """Run a shell command and return stdout, or None on error."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return stdout.decode().strip()
        except Exception as e:
            logger.debug("_run_cmd(%s) failed: %s", cmd, e)
        return None

    async def _write_journal_entry(
        self,
        trigger: str,
        channel: str | None,
        event_summary: str,
        spoke: bool,
    ) -> None:
        """Write a journal entry (best-effort)."""
        try:
            entry = self.mind.make_journal_entry(
                trigger=trigger,
                channel=channel,
                observation=event_summary[:200],
                spoke=spoke,
            )
            self.mind.write_journal(entry)
        except Exception as e:
            logger.warning("Failed to write journal entry: %s", e)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("discord").setLevel(logging.WARNING)

    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()

    bot = Dev.from_config("agent.yaml")

    async def _main():
        await bot.start()
        bot.watch_config("agent.yaml")
        try:
            await bot._run_task
        except asyncio.CancelledError:
            pass

    asyncio.run(_main())
