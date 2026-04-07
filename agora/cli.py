"""CLI entry point for `agora init <name>` scaffolding command."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from pathlib import Path

AGENT_PY_TEMPLATE = '''\
"""%(name)s — an Agora agent."""

from agora import Agora


class %(class_name)s(Agora):
    async def on_message(self, message):
        # Return a string to post as a reply, or None to stay silent.
        if message.is_mention:
            return f"Hello {message.author_name}, you said: {message.content}"
        return None


if __name__ == "__main__":
    bot = %(class_name)s.from_config("agent.yaml")
    bot.run()
'''

AGENT_YAML_TEMPLATE = """\
# %(name)s configuration
token_env: DISCORD_BOT_TOKEN

channels:
  general: mention-only
"""

RUN_SH_TEMPLATE = """\
#!/usr/bin/env bash
# Start %(name)s
export DISCORD_BOT_TOKEN="your-token-here"
python agent.py
"""


def _slugify(name: str) -> str:
    """Convert a name to a safe directory/module identifier."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        raise ValueError(f"Name '{name}' produces an empty slug")
    return slug


def _to_class_name(slug: str) -> str:
    """Convert a slug like 'my-bot' to 'MyBot'."""
    return "".join(part.capitalize() for part in re.split(r"[-_]", slug) if part)


def init_agent(name: str, base_dir: Path | None = None) -> Path:
    """Create a new agent project directory with starter files.

    Returns the path to the created directory.
    Raises FileExistsError if the directory already exists.
    """
    slug = _slugify(name)
    class_name = _to_class_name(slug)

    parent = base_dir or Path.cwd()
    project_dir = parent / slug

    if project_dir.exists():
        raise FileExistsError(f"Directory '{project_dir}' already exists")

    project_dir.mkdir(parents=True)

    ctx = {"name": slug, "class_name": class_name}

    (project_dir / "agent.py").write_text(AGENT_PY_TEMPLATE % ctx)
    (project_dir / "agent.yaml").write_text(AGENT_YAML_TEMPLATE % ctx)

    run_sh = project_dir / "run.sh"
    run_sh.write_text(RUN_SH_TEMPLATE % ctx)
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return project_dir


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agora", description="Agora CLI")
    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="Create a new agent project")
    init_parser.add_argument("name", help="Name for the new agent project")

    args = parser.parse_args(argv)

    if args.command == "init":
        try:
            path = init_agent(args.name)
            print(f"Created agent project at {path}")
        except (FileExistsError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
