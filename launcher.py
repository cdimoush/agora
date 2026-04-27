"""launcher.py — drive one airlock task end-to-end.

  user → run.sh → launcher.py → (worktree | broker | code-container | agent-container)

The launcher does not run inside any container. It runs on the host and:

  1. Creates a git worktree of the user's repo at <repo>/../airlock-<id>/
     on a fresh branch airlock/<id>.
  2. Starts the host broker (broker.py) listening on /tmp/airlock-<id>.sock.
  3. Starts the *code* container with the worktree bind-mounted into
     /workspace, --network none, read-only root with tmpfs scratch space.
  4. Starts the *agent* container with /var/run/docker.sock (so it can
     `docker exec` into the code container — the airlock) and the broker
     socket bind-mounted at /broker.sock.
  5. Runs Claude Code inside the agent container with a system prompt that
     teaches it about the airlock and the broker.
  6. On exit (clean or signal), tears it all down.

Usage:
    launcher.py <repo-path> "<task description>"

Stdlib only. ~250 lines.
"""

from __future__ import annotations

import argparse
import atexit
import os
import re
import shlex
import shutil
import signal
import string
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

CODE_IMAGE = "airlock-code:latest"
AGENT_IMAGE = "airlock-agent:latest"
HERE = Path(__file__).resolve().parent

# Identifiers must be docker-name-safe and broker-branch-safe.
SAFE = set(string.ascii_lowercase + string.digits + "-")


def _new_task_id() -> str:
    return f"t{uuid.uuid4().hex[:8]}"


def _safe_slug(s: str) -> str:
    s = "".join(c if c in SAFE else "-" for c in s.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:24] or "task"


# --------------------------------------------------------------------------- #
# Subprocess helpers
# --------------------------------------------------------------------------- #


def _run(cmd: list[str], *, check: bool = True, cwd: str | None = None,
         capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command, return CompletedProcess. Raises if check and rc != 0."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
    )


def _docker(*args: str, capture: bool = True,
            check: bool = True) -> subprocess.CompletedProcess:
    return _run(["docker", *args], check=check, capture=capture)


# --------------------------------------------------------------------------- #
# Worktree (lifted from agora cli.py:444-490, _worktrees_dir bug excised)
# --------------------------------------------------------------------------- #


def worktree_create(repo: Path, task_id: str) -> tuple[Path, str]:
    """Create a worktree at <repo>/../airlock-<id> on branch airlock/<id>.

    Returns (worktree_path, branch_name).
    """
    if not (repo / ".git").exists():
        raise SystemExit(f"ERROR: {repo} is not a git repo (.git/ missing).")

    wt_dir = repo.parent / f"airlock-{task_id}"
    branch = f"airlock/{task_id}"

    if wt_dir.exists():
        raise SystemExit(f"ERROR: worktree {wt_dir} already exists.")

    # We need a base ref. Prefer the current branch; fall back to HEAD.
    head = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo)).stdout.strip()
    base = head if head and head != "HEAD" else "HEAD"

    proc = _run(
        ["git", "worktree", "add", str(wt_dir), "-b", branch, base],
        cwd=str(repo), check=False,
    )
    if proc.returncode != 0:
        # Branch may already exist from a previous failed run.
        if "already exists" in proc.stderr:
            proc = _run(
                ["git", "worktree", "add", str(wt_dir), branch],
                cwd=str(repo), check=False,
            )
        if proc.returncode != 0:
            raise SystemExit(f"ERROR: git worktree add failed:\n{proc.stderr.strip()}")

    return wt_dir, branch


def worktree_remove(repo: Path, wt_dir: Path, branch: str) -> None:
    if wt_dir.exists():
        _run(["git", "worktree", "remove", str(wt_dir), "--force"],
             cwd=str(repo), check=False)
    _run(["git", "branch", "-D", branch], cwd=str(repo), check=False)


# --------------------------------------------------------------------------- #
# Container lifecycle
# --------------------------------------------------------------------------- #


@dataclass
class TaskState:
    task_id: str
    repo: Path
    worktree: Path
    branch: str
    sock_path: Path
    code_name: str
    agent_name: str
    broker_proc: subprocess.Popen | None = None
    started: list[str] = field(default_factory=list)  # container names actually started
    cleaned: bool = False


def start_broker(state: TaskState) -> None:
    """Start broker.py as a subprocess on the host."""
    if state.sock_path.exists():
        state.sock_path.unlink()
    state.broker_proc = subprocess.Popen(
        ["python3", str(HERE / "broker.py"), "--socket", str(state.sock_path)],
        stdout=sys.stderr,  # broker logs to stderr; pipe to ours
        stderr=sys.stderr,
    )
    # Wait briefly for the socket to appear.
    for _ in range(50):
        if state.sock_path.exists():
            return
        time.sleep(0.05)
    raise SystemExit("ERROR: broker did not bind its socket within 2.5s")


def start_code_container(state: TaskState) -> None:
    """Run the sealed code container."""
    # Run as the host user so files created in the bind-mounted worktree
    # (pytest caches, agent edits) belong to the host user, not root.
    uid = os.getuid()
    gid = os.getgid()
    cmd = [
        "run", "-d", "--rm",
        "--name", state.code_name,
        "--user", f"{uid}:{gid}",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=256m",
        "--tmpfs", "/var/cache:rw,size=128m",
        "--tmpfs", f"/home/u{uid}:rw,size=64m",
        "-e", f"HOME=/home/u{uid}",
        "-v", f"{state.worktree}:/workspace:rw",
        "-w", "/workspace",
        CODE_IMAGE,
    ]
    proc = _docker(*cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"ERROR: failed to start code container:\n{proc.stderr}")
    state.started.append(state.code_name)


def start_agent_container(state: TaskState) -> None:
    """Run the agent container, mounting the broker socket and docker socket."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY missing in launcher env.")

    uid = os.getuid()
    gid = os.getgid()
    cmd = [
        "run", "-d", "--rm",
        "--name", state.agent_name,
        "--user", f"{uid}:{gid}",
        "--tmpfs", f"/home/u{uid}:rw,size=128m",
        "-e", f"HOME=/home/u{uid}",
        "-e", f"ANTHROPIC_API_KEY={api_key}",
        "-e", f"CODE_CONTAINER={state.code_name}",
        "-e", f"AIRLOCK_BRANCH={state.branch}",
        # Broker runs on the host, so AIRLOCK_WORKTREE must be the *host*
        # path. The agent never touches this path itself — it just passes
        # the env through broker_client.sh to the host broker.
        "-e", f"AIRLOCK_WORKTREE={state.worktree}",
        # Worktree mounted read-write so claude's native Read/Edit/Write
        # tools work directly. The airlock still applies for execution
        # (pytest, git, etc.) — see the system prompt.
        "-v", f"{state.worktree}:/workspace:rw",
        "-v", f"{state.sock_path}:/broker.sock:rw",
        "-v", "/var/run/docker.sock:/var/run/docker.sock:rw",
        AGENT_IMAGE,
    ]
    proc = _docker(*cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"ERROR: failed to start agent container:\n{proc.stderr}")
    state.started.append(state.agent_name)


def stop_container(name: str) -> None:
    _docker("stop", "-t", "5", name, check=False)


# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #


def cleanup(state: TaskState, *, prompt_worktree: bool = True) -> None:
    if state.cleaned:
        return
    state.cleaned = True
    print("\n[launcher] cleaning up...", file=sys.stderr)

    for name in state.started:
        stop_container(name)

    if state.broker_proc and state.broker_proc.poll() is None:
        state.broker_proc.terminate()
        try:
            state.broker_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            state.broker_proc.kill()
    if state.sock_path.exists():
        try:
            state.sock_path.unlink()
        except OSError:
            pass

    if state.worktree.exists() and prompt_worktree and sys.stdin.isatty():
        try:
            ans = input(f"[launcher] remove worktree {state.worktree}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans == "y":
            worktree_remove(state.repo, state.worktree, state.branch)
            print(f"[launcher] removed worktree and branch {state.branch}", file=sys.stderr)
        else:
            print(f"[launcher] worktree kept at {state.worktree}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# System prompt for Claude (teaches it the airlock)
# --------------------------------------------------------------------------- #


SYSTEM_PROMPT = textwrap.dedent("""\
    You are Claude Code running in the AGENT container of the agent-airlock-toy.

    The project worktree is mounted at /workspace in BOTH this container and
    a separate sealed container called $CODE_CONTAINER. The two paths point
    at the same files on disk. This container has internet and the API key;
    $CODE_CONTAINER has --network none and no secrets.

    Use your tools as follows:

    - For READING and EDITING files: use your native Read / Edit / Write
      tools on /workspace directly. Files there are real project files.

    - For EXECUTING anything that runs code — pytest, git, build commands,
      arbitrary scripts — you MUST shell out into the sealed container:

          docker exec $CODE_CONTAINER bash -c '<your command>'

      Do NOT run pytest, git, build, or other code from this container.
      Editing is information; execution is action — only execution needs
      the airlock.

    Examples:
        # editing — use native tools
        Read   /workspace/calc.py
        Edit   /workspace/calc.py    (old → new)

        # executing — must go through the airlock
        docker exec $CODE_CONTAINER bash -c 'cd /workspace && pytest -q'
        docker exec $CODE_CONTAINER bash -c 'cd /workspace && git diff'
        docker exec $CODE_CONTAINER bash -c 'cd /workspace && git add -A && git commit -m "fix"'

    The code container has --network none, so package installs from the
    internet will fail there. Project deps are pre-installed.

    To push to the real remote at the end, you DO NOT have ssh keys here.
    Use the host broker. From this (agent) container run:

        broker_client.sh git_push $AIRLOCK_BRANCH

    The branch you should push is in $AIRLOCK_BRANCH (something like
    airlock/<task-id>). The broker rejects any other branch name.

    Your task is provided in the user message. When you've completed it,
    push the branch and stop.
""")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="airlock-toy launcher")
    p.add_argument("repo", help="path to a git repo")
    p.add_argument("task", help="task description for Claude")
    p.add_argument("--no-claude", action="store_true",
                   help="set up containers but skip the Claude run "
                        "(useful for manual testing)")
    args = p.parse_args(argv)

    repo = Path(args.repo).resolve()
    task_id = _new_task_id()
    sock_path = Path(f"/tmp/airlock-{task_id}.sock")

    state = TaskState(
        task_id=task_id,
        repo=repo,
        worktree=Path(),  # filled in below
        branch="",        # filled in below
        sock_path=sock_path,
        code_name=f"airlock-code-{task_id}",
        agent_name=f"airlock-agent-{task_id}",
    )

    def _signal_handler(signum, _frame):
        print(f"\n[launcher] caught signal {signum}", file=sys.stderr)
        cleanup(state, prompt_worktree=False)
        sys.exit(130)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(lambda: cleanup(state, prompt_worktree=False))

    # 1. Worktree
    print(f"[launcher] task={task_id}  repo={repo}", file=sys.stderr)
    state.worktree, state.branch = worktree_create(repo, task_id)
    print(f"[launcher] worktree {state.worktree}  branch {state.branch}",
          file=sys.stderr)

    # 2. Broker
    start_broker(state)
    print(f"[launcher] broker on {sock_path}", file=sys.stderr)

    # 3. Code container
    start_code_container(state)
    print(f"[launcher] code container {state.code_name} (network none)",
          file=sys.stderr)

    # 4. Agent container
    start_agent_container(state)
    print(f"[launcher] agent container {state.agent_name} (docker.sock + broker.sock mounted)",
          file=sys.stderr)

    if args.no_claude:
        print(textwrap.dedent(f"""
            [launcher] containers up. attach with:
                docker exec -it {state.code_name} bash       # sealed
                docker exec -it {state.agent_name} bash      # has docker, broker_client.sh
            Ctrl-C here to clean up.
        """).rstrip(), file=sys.stderr)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            return 130

    # 5. Run Claude inside the agent container.
    full_prompt = SYSTEM_PROMPT + "\n\n# Task\n\n" + args.task
    claude_cmd = [
        "docker", "exec",
        "-e", f"CODE_CONTAINER={state.code_name}",
        "-e", f"AIRLOCK_BRANCH={state.branch}",
        "-e", f"AIRLOCK_WORKTREE={state.worktree}",
        state.agent_name,
        "claude", "-p", full_prompt,
        "--permission-mode", "bypassPermissions",
    ]
    print(f"[launcher] running claude with task: {args.task}", file=sys.stderr)
    proc = subprocess.run(claude_cmd, check=False)

    print(f"[launcher] claude exited rc={proc.returncode}", file=sys.stderr)

    # 6. Cleanup with worktree prompt (interactive only).
    cleanup(state, prompt_worktree=True)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
