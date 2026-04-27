"""broker.py — host-side daemon for privileged ops.

The agent container has no host SSH key, no cloud credentials, no host
filesystem. When it needs to do something privileged (e.g. `git push` to a
real remote), it sends a JSON-line request to /tmp/airlock.sock; this
daemon executes the op on the host, with the host's SSH agent, and returns
a JSON-line reply.

Allowed ops (toy):
    git_push   — push a branch to origin (branch must match airlock/*)
    git_fetch  — fetch a branch from origin

Each request is one connection; one line in, one line out, then close.
There is no auth on the socket itself — its filesystem permissions plus
bind-mount-into-the-agent-container *is* the auth.

Run:
    python3 broker.py [--socket /tmp/airlock.sock]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_SOCK = "/tmp/airlock.sock"
BRANCH_RE = re.compile(r"^airlock/[a-z0-9][a-z0-9-]*$")


def log(msg: str) -> None:
    print(f"[broker] {msg}", file=sys.stderr, flush=True)


def reply(conn: socket.socket, payload: dict) -> None:
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    try:
        conn.sendall(line.encode())
    except OSError:
        pass


def handle(conn: socket.socket) -> None:
    """Process a single request, send a single reply, close."""
    try:
        # Read one line. Bound the request size; broker is for tiny intents.
        buf = bytearray()
        while b"\n" not in buf and len(buf) < 4096:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
        line = bytes(buf).split(b"\n", 1)[0].decode(errors="replace").strip()

        if not line:
            reply(conn, {"ok": False, "stderr": "empty request"})
            return

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            reply(conn, {"ok": False, "stderr": f"bad json: {e}"})
            return

        op = req.get("op")
        branch = req.get("branch", "")
        worktree = req.get("worktree", "")

        log(f"request: op={op!r} branch={branch!r} worktree={worktree!r}")

        if op not in ("git_push", "git_fetch"):
            reply(conn, {"ok": False, "stderr": f"unsupported op: {op!r}"})
            return

        if not BRANCH_RE.match(branch or ""):
            reply(
                conn,
                {
                    "ok": False,
                    "stderr": (
                        f"branch must match airlock/<slug>; got {branch!r}"
                    ),
                },
            )
            return

        wt = Path(worktree)
        if not wt.is_absolute() or not wt.is_dir() or not (wt / ".git").exists():
            reply(
                conn,
                {
                    "ok": False,
                    "stderr": f"worktree not a git repo on host: {worktree!r}",
                },
            )
            return

        if op == "git_push":
            cmd = ["git", "push", "-u", "origin", branch]
        else:  # git_fetch
            cmd = ["git", "fetch", "origin", branch]

        proc = subprocess.run(
            cmd,
            cwd=str(wt),
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = proc.returncode == 0
        log(f"  exit={proc.returncode} ok={ok}")
        reply(
            conn,
            {
                "ok": ok,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            },
        )
    except subprocess.TimeoutExpired:
        reply(conn, {"ok": False, "stderr": "timed out (>120s)"})
    except Exception as e:  # broad on purpose; never crash the daemon
        reply(conn, {"ok": False, "stderr": f"broker error: {e!r}"})
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve(sock_path: str) -> None:
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    # Anyone with the bind-mount can connect. We could 0600 it, but the
    # bind-mount-into-the-agent-container is the auth boundary.
    os.chmod(sock_path, 0o600)
    server.listen(8)
    log(f"listening on {sock_path}")

    try:
        while True:
            conn, _ = server.accept()
            t = threading.Thread(target=handle, args=(conn,), daemon=True)
            t.start()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        try:
            server.close()
        except OSError:
            pass
        if os.path.exists(sock_path):
            os.unlink(sock_path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="airlock-toy host broker")
    p.add_argument("--socket", default=DEFAULT_SOCK, help="UDS path")
    args = p.parse_args(argv)
    serve(args.socket)
    return 0


if __name__ == "__main__":
    sys.exit(main())
