"""CLI entry point for Agora commands (init, run)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import signal
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

CONTAINER_AGENT_YAML_TEMPLATE = """\
# %(name)s configuration
token_env: DISCORD_BOT_TOKEN

channels:
  general: mention-only

context:
  backend: container
"""

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim
RUN pip install agora
WORKDIR /agent
COPY . .
CMD ["python", "agent.py"]
"""

ENV_EXAMPLE_TEMPLATE = """\
# Copy to .env and fill in values
DISCORD_BOT_TOKEN=your-token-here
# Add LLM API keys below
"""

GITIGNORE_TEMPLATE = """\
.env
__pycache__/
*.pyc
"""

CONTAINER_RUN_SH_TEMPLATE = """\
#!/usr/bin/env bash
# Start %(name)s
set -euo pipefail
if command -v agora &>/dev/null; then
    agora run "$@"
else
    python agent.py
fi
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


def init_agent(name: str, base_dir: Path | None = None, container: bool = False) -> Path:
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

    if container:
        (project_dir / "agent.yaml").write_text(CONTAINER_AGENT_YAML_TEMPLATE % ctx)
        (project_dir / "Dockerfile").write_text(DOCKERFILE_TEMPLATE)
        (project_dir / ".env.example").write_text(ENV_EXAMPLE_TEMPLATE)
        (project_dir / ".gitignore").write_text(GITIGNORE_TEMPLATE)

        run_sh = project_dir / "run.sh"
        run_sh.write_text(CONTAINER_RUN_SH_TEMPLATE % ctx)
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    else:
        (project_dir / "agent.yaml").write_text(AGENT_YAML_TEMPLATE % ctx)

        run_sh = project_dir / "run.sh"
        run_sh.write_text(RUN_SH_TEMPLATE % ctx)
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return project_dir


def run_agent(config_path: str = "agent.yaml", runtime_override: str | None = None, rebuild: bool = False) -> None:
    """Run an agent based on its agent.yaml configuration."""
    from agora.config import Config, ConfigError
    from agora.context import ContainerContext, RuntimeNotFound

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        print(f"Error: {config_path} not found. Run 'agora init' first.", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = Config.from_yaml(cfg_path)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if cfg.context_backend is None:
        # Local mode — just run agent.py
        agent_py = cfg_path.parent / "agent.py"
        if not agent_py.exists():
            print(f"Error: agent.py not found in {cfg_path.parent}", file=sys.stderr)
            sys.exit(1)
        os.execvp(sys.executable, [sys.executable, str(agent_py)])
    else:
        # Container mode
        image = cfg.context_image or cfg_path.parent.name
        runtime = runtime_override or cfg.context_runtime  # None = auto-detect
        ctx = ContainerContext(
            image=image,
            runtime=runtime,
            build_path=str(cfg_path.parent),
        )

        async def _run_container() -> int:
            try:
                rt = await ctx.runtime()
            except RuntimeNotFound as e:
                print(
                    f"Error: {e}\n\n"
                    "Install podman (recommended) or docker.\n"
                    "Or remove the context section from agent.yaml to run locally.",
                    file=sys.stderr,
                )
                return 1

            # Build
            print(f"Building image '{image}' with {rt}...")
            try:
                await ctx.build_image(no_cache=rebuild)
            except Exception as e:
                print(f"Error building image: {e}", file=sys.stderr)
                return 1

            # Start
            print(f"Starting container...")
            try:
                container_id = await ctx.start()
            except Exception as e:
                print(f"Error starting container: {e}", file=sys.stderr)
                return 1

            # Stream logs
            log_proc = await asyncio.create_subprocess_exec(
                rt, "logs", "-f", container_id,
                stdout=None,  # inherit — goes to terminal
                stderr=None,
            )

            # Wait for container to exit
            wait_proc = await asyncio.create_subprocess_exec(
                rt, "wait", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await wait_proc.communicate()
            log_proc.terminate()

            exit_code_str = stdout.decode().strip()
            try:
                return int(exit_code_str)
            except ValueError:
                return 0

        loop = asyncio.new_event_loop()

        # Handle signals
        def _shutdown(signum, frame):
            print("\nStopping container...")
            loop.run_until_complete(ctx.stop())
            sys.exit(130)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        exit_code = loop.run_until_complete(_run_container())
        sys.exit(exit_code)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agora", description="Agora CLI")
    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="Create a new agent project")
    init_parser.add_argument("name", help="Name for the new agent project")
    init_parser.add_argument("--container", action="store_true", help="Generate container files (Dockerfile, .env.example, etc.)")

    run_parser = sub.add_parser("run", help="Run an agent from its config")
    run_parser.add_argument("--config", default="agent.yaml", help="Path to agent.yaml")
    run_parser.add_argument("--runtime", choices=["podman", "docker"], help="Override container runtime")
    run_parser.add_argument("--rebuild", action="store_true", help="Force image rebuild (no cache)")

    args = parser.parse_args(argv)

    if args.command == "init":
        try:
            path = init_agent(args.name, container=args.container)
            print(f"Created agent project at {path}")
        except (FileExistsError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "run":
        run_agent(
            config_path=args.config,
            runtime_override=args.runtime,
            rebuild=args.rebuild,
        )
    else:
        parser.print_help()
        sys.exit(1)
