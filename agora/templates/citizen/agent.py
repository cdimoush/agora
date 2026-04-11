"""{{name}} -- a Claude-powered Agora citizen."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from agora import Agora, Message
from agora.errors import ErrorContext
from mind import Mind

logger = logging.getLogger("agora.{{name}}")


class {{class_name}}(Agora):
    """A citizen who watches, remembers, and speaks when moved."""

    def __init__(self, config, project_dir: Path | None = None):
        super().__init__(config)
        self._project_dir = project_dir or Path(__file__).resolve().parent
        self.mind = Mind(self._project_dir)

    @classmethod
    def from_config(cls, path: str) -> "{{class_name}}":
        from agora.config import Config

        config = Config.from_yaml(path)
        project_dir = Path(path).resolve().parent
        return cls(config, project_dir=project_dir)

    async def on_message(self, message: Message) -> str | None:
        """Respond to an @mention or subscribed message."""
        logger.info("on_message from %s in #%s", message.author_name, message.channel_name)

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
        response = await self._call_claude(prompt)

        if response:
            await self._write_journal_entry(
                trigger="reactive",
                channel=message.channel_name,
                event_summary=f"In #{message.channel_name}, {message.author_name} said: {message.content[:100]}. I replied: {response[:100]}",
                spoke=True,
            )

        return response

    async def on_error(self, error: Exception, context: ErrorContext) -> str | None:
        """Fail gracefully."""
        logger.error("Error [%s]: %s", context.stage, error)
        return "something went wrong, give me a moment"

    async def _call_claude(self, prompt: str, budget: str = "0.25") -> str | None:
        """Call Claude CLI and return the response text."""
        self.emit("inference.request",
            backend="claude-cli", model="sonnet", prompt=prompt,
        )

        start = time.monotonic()

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--model", "sonnet",
            "--max-budget-usd", budget,
            "--dangerously-skip-permissions",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
            env=env,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            await proc.wait()
            elapsed_ms = (time.monotonic() - start) * 1000
            self.emit("inference.error",
                backend="claude-cli", error="timeout",
                duration_ms=round(elapsed_ms, 2),
            )
            logger.warning("Claude subprocess timed out")
            return None

        elapsed_ms = (time.monotonic() - start) * 1000

        if proc.returncode != 0:
            self.emit("inference.error",
                backend="claude-cli", error=f"exit={proc.returncode}",
                duration_ms=round(elapsed_ms, 2),
            )
            logger.error("Claude exit=%d stderr=%s", proc.returncode, stderr.decode()[:500])
            return None

        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError:
            self.emit("inference.error",
                backend="claude-cli", error="json_decode",
                duration_ms=round(elapsed_ms, 2),
            )
            logger.error("Failed to parse Claude JSON output")
            return None

        result = data.get("result", "") or None
        self.emit("inference.response",
            backend="claude-cli",
            model=data.get("model", "sonnet"),
            response=result or "",
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            cost_usd=data.get("total_cost_usd"),
            duration_ms=round(elapsed_ms, 2),
        )

        return result

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

    bot = {{class_name}}.from_config("agent.yaml")

    async def _main():
        await bot.start()
        try:
            await bot._run_task
        except asyncio.CancelledError:
            pass

    asyncio.run(_main())
