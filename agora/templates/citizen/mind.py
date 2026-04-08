"""Prompt construction and journal management for {{name}}."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agora.{{name}}.mind")

JOURNAL_MAX_ENTRIES = 100
JOURNAL_READ_LIMIT = 20


class Mind:
    """Prompt engine and journal layer.

    Owns three concerns:
    1. Journal I/O (read, write, rotate)
    2. Prompt construction (reactive, scan)
    3. Persona text (loaded from CLAUDE.md at init)
    """

    def __init__(self, project_dir: Path):
        self._project_dir = project_dir
        self._journal_path = project_dir / "journal.jsonl"
        self._archive_path = project_dir / "journal.archive.jsonl"
        self._persona = self._load_persona()

    def _load_persona(self) -> str:
        claude_md = self._project_dir / "CLAUDE.md"
        if claude_md.exists():
            return claude_md.read_text()
        return ""

    # -- Journal I/O --

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

    # -- Prompt Builders --

    def build_reactive_prompt(
        self,
        author_name: str,
        message_content: str,
        channel_name: str,
        history_lines: list[str],
        roster: set[str],
        journal_entries: list[dict],
    ) -> str:
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
        parts.append("Respond in character. Output only your reply, nothing else.")

        return "\n".join(parts)

    # -- Helpers --

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
