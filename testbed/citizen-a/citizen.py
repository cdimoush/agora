"""CitizenBot — Claude-powered conversational agent for Agora."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agora import AgoraBot, Message

logger = logging.getLogger("agora.citizen")

SYSTEM_PROMPT = (
    "You are in a Discord conversation with humans and other AI agents. "
    "Keep responses to 1-2 sentences. Be conversational — no markdown headers, "
    "no bullet lists, no assistant-speak. Sound like a person texting."
)


class CitizenBot(AgoraBot):
    """A citizen that generates responses via claude -p subprocess."""

    def __init__(self, config, project_dir: Path | None = None):
        super().__init__(config)
        self._project_dir = project_dir or Path(__file__).resolve().parent

    @classmethod
    def from_config(cls, path: str) -> CitizenBot:
        from agora.config import Config

        config = Config.from_yaml(path)
        project_dir = Path(path).resolve().parent
        return cls(config, project_dir=project_dir)

    async def should_respond(self, message: Message) -> bool:
        if message.is_mention:
            return True
        # In subscribe channels, respond to all messages.
        # Exchange cap in the dispatch pipeline prevents infinite loops.
        return True

    async def generate_response(self, message: Message) -> str | None:
        channel = self._client.get_channel(message.channel_id)
        if not channel:
            return None

        # Build prompt from recent channel history
        history_lines = []
        async for msg in channel.history(limit=10):
            if msg.id == message.id:
                continue
            role = "bot" if msg.author.bot else "human"
            history_lines.append(f"[{role}] {msg.author.display_name}: {msg.content}")
        history_lines.reverse()

        prompt = f"Channel: #{message.channel_name}\n"
        if history_lines:
            prompt += "Recent messages:\n" + "\n".join(history_lines) + "\n\n"
        prompt += f"{message.author_name}: {message.content}"

        return await self._call_claude(prompt)

    async def _call_claude(self, prompt: str) -> str | None:
        """Spawn claude -p subprocess and return the response text."""
        with self.span("llm_call", model="haiku", prompt_length=len(prompt)) as s:
            s["prompt_preview"] = prompt[:200]

            env = os.environ.copy()
            env.pop("CLAUDECODE", None)  # Prevent nested session error

            cmd = [
                "claude", "-p", prompt,
                "--output-format", "json",
                "--model", "haiku",
                "--max-budget-usd", "0.02",
                "--append-system-prompt", SYSTEM_PROMPT,
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
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=60
                )
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                await proc.wait()
                s["decision"] = "error"
                s["error"] = "timeout"
                logger.warning("Claude subprocess timed out")
                return None

            if proc.returncode != 0:
                s["decision"] = "error"
                s["error"] = f"exit={proc.returncode}"
                logger.error(
                    "Claude exit=%d stderr=%s stdout=%s",
                    proc.returncode,
                    stderr.decode()[:500],
                    stdout.decode()[:500],
                )
                return None

            try:
                data = json.loads(stdout.decode())
            except json.JSONDecodeError:
                s["decision"] = "error"
                s["error"] = "json_decode"
                logger.error("Failed to parse Claude JSON output")
                return None

            result = data.get("result", "") or None
            if result:
                s["decision"] = "pass"
                s["response_length"] = len(result)
                s["response_preview"] = result[:200]
            else:
                s["decision"] = "empty"

            return result


if __name__ == "__main__":
    from pathlib import Path

    config_path = str(Path(__file__).resolve().parent / "agent.yaml")
    bot = CitizenBot.from_config(config_path)
    bot.run()
