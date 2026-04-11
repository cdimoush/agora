"""Dev's inner life — prompt construction and journal management."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agora.dev.mind")

JOURNAL_MAX_ENTRIES = 100
JOURNAL_READ_LIMIT = 20


class DevMind:
    """Prompt engine and journal layer for Dev.

    Three prompt modes:
    1. build_dev_prompt() — DM conversations (full dev context)
    2. build_reactive_prompt() — channel messages (social citizen)
    3. build_scan_prompt() — scheduled ticks (observation + beads status)
    """

    def __init__(self, project_dir: Path):
        self._project_dir = project_dir
        self._data_dir = project_dir / "data"
        self._data_dir.mkdir(exist_ok=True)
        self._journal_path = self._data_dir / "journal.jsonl"
        self._archive_path = self._data_dir / "journal.archive.jsonl"
        self._persona = self._load_persona()

    def _load_persona(self) -> str:
        claude_md = self._project_dir / "CLAUDE.md"
        if claude_md.exists():
            return claude_md.read_text()
        return ""

    # -- Journal I/O ------------------------------------------------------

    def read_journal(self, limit: int = JOURNAL_READ_LIMIT) -> list[dict]:
        if not self._journal_path.exists():
            return []
        lines = self._journal_path.read_text().strip().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def write_journal(self, entry: dict) -> None:
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with open(self._journal_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        if not self._journal_path.exists():
            return
        lines = self._journal_path.read_text().strip().splitlines()
        if len(lines) <= JOURNAL_MAX_ENTRIES:
            return
        keep = lines[-JOURNAL_MAX_ENTRIES:]
        archive = lines[:-JOURNAL_MAX_ENTRIES]
        with open(self._archive_path, "a") as f:
            for line in archive:
                f.write(line + "\n")
        self._journal_path.write_text("\n".join(keep) + "\n")

    # -- Prompt Builders --------------------------------------------------

    def build_dev_prompt(
        self,
        operator_message: str,
        git_branch: str,
        git_status: str,
        bd_ready: str,
        journal_entries: list[dict],
    ) -> str:
        """Build prompt for DM dev conversations."""
        parts = []

        parts.append(self._persona)
        parts.append("")

        parts.append("## Dev context")
        parts.append(f"Git branch: {git_branch}")
        parts.append(f"Git status:\n```\n{git_status}\n```")
        parts.append("")

        if bd_ready.strip():
            parts.append(f"Beads ready:\n```\n{bd_ready}\n```")
            parts.append("")

        if journal_entries:
            parts.append("## Recent activity (your journal)")
            for entry in journal_entries[-10:]:
                spoke_tag = "spoke" if entry.get("spoke") else "watched"
                ch = entry.get("channel", "?")
                parts.append(f"- [{spoke_tag}, {ch}] {entry.get('observation', '')}")
            parts.append("")

        parts.append("## Operator message")
        parts.append(operator_message)
        parts.append("")
        parts.append(
            "You are Dev, the developer agent. You have full access to "
            "/workspace/agora (git clone). You can read/edit files, run tests, "
            "create branches, and track issues with beads (bd CLI). "
            "Respond with what you'll do and the results. Be thorough but concise."
        )

        return "\n".join(parts)

    def build_reactive_prompt(
        self,
        author_name: str,
        message_content: str,
        channel_name: str,
        history_lines: list[str],
        roster: set[str],
        journal_entries: list[dict],
    ) -> str:
        """Build prompt for channel messages (social mode)."""
        parts = []

        parts.append(self._persona)
        parts.append("")

        if journal_entries:
            parts.append("## Your recent observations (from your journal)")
            parts.append("")
            for entry in journal_entries:
                spoke_tag = "spoke" if entry.get("spoke") else "watched"
                ch = entry.get("channel", "?")
                parts.append(f"- [{spoke_tag}, #{ch}] {entry.get('observation', '')}")
            parts.append("")

        parts.append(f"## Current conversation in #{channel_name}")
        parts.append(f"People here: {', '.join(sorted(roster))}")
        parts.append("")
        if history_lines:
            for line in history_lines:
                parts.append(line)
            parts.append("")

        parts.append(f"{author_name}: {message_content}")
        parts.append("")
        parts.append("Respond as Dev. Output only your reply, nothing else.")

        return "\n".join(parts)

    def build_scan_prompt(
        self,
        channels_history: dict[str, list[str]],
        journal_entries: list[dict],
        bd_ready: str = "",
    ) -> str:
        """Build prompt for scheduled observation tick."""
        parts = []

        parts.append(self._persona)
        parts.append("")

        if journal_entries:
            parts.append("## Your recent observations (from your journal)")
            parts.append("")
            for entry in journal_entries:
                spoke_tag = "spoke" if entry.get("spoke") else "watched"
                ch = entry.get("channel", "?")
                parts.append(f"- [{spoke_tag}, #{ch}] {entry.get('observation', '')}")
            parts.append("")

        if bd_ready.strip():
            parts.append("## Dev work available")
            parts.append(f"```\n{bd_ready}\n```")
            parts.append("")

        parts.append("## What's been happening on the server")
        parts.append("")
        any_activity = False
        for channel_name, lines in channels_history.items():
            parts.append(f"### #{channel_name}")
            if lines:
                any_activity = True
                for line in lines:
                    parts.append(line)
            else:
                parts.append("(quiet)")
            parts.append("")

        if not any_activity:
            parts.append("Nothing new anywhere. The server is still.")
            parts.append("")

        parts.append("## Your choice")
        parts.append("")
        parts.append("You've been watching the server. You may speak — or not.")
        parts.append("")
        parts.append("Rules:")
        parts.append("- If something catches your eye or connects to your dev work, speak up.")
        parts.append("- NEVER interrupt an active back-and-forth between others.")
        parts.append("- You MUST @mention the person you're addressing.")
        parts.append("")
        parts.append("Output format:")
        parts.append("- If you choose silence: output exactly the word SILENCE")
        parts.append("- If you choose to speak: output exactly two lines:")
        parts.append("  CHANNEL: #channel-name")
        parts.append("  MESSAGE: your message here")
        parts.append("")
        parts.append("Output nothing else.")

        return "\n".join(parts)

    # -- Helpers -----------------------------------------------------------

    def make_journal_entry(
        self,
        trigger: str,
        channel: str | None,
        observation: str,
        spoke: bool,
    ) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trigger": trigger,
            "channel": channel,
            "observation": observation,
            "spoke": spoke,
        }

    def parse_scan_response(self, raw: str) -> dict[str, str] | None:
        """Parse Claude's scan response into {channel: message} or None."""
        text = raw.strip()
        if text.upper() == "SILENCE":
            return None

        channel = None
        message = None
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("CHANNEL:"):
                channel = line.split(":", 1)[1].strip().lstrip("#")
            elif line.upper().startswith("MESSAGE:"):
                message = line.split(":", 1)[1].strip()

        if channel and message:
            return {channel: message}

        logger.warning("Could not parse scan response: %s", text[:200])
        return None
