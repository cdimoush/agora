#!/usr/bin/env bash
# broker_client.sh — agent-container side of the host broker.
#
# Sends one JSON line to the broker at /broker.sock and prints the reply.
# This is the only path through which the agent can ask the host to do
# privileged things (like `git push` with the real SSH key).
#
# Usage:
#   broker_client.sh <op> [<branch>]
#
# Ops:
#   git_push <branch>   — push <branch> to origin (branch must match airlock/*)
#   git_fetch <branch>  — fetch <branch> from origin
#
# Examples:
#   broker_client.sh git_push airlock/test-task
#   broker_client.sh git_fetch airlock/test-task

set -euo pipefail

OP="${1:-}"
BRANCH="${2:-}"

if [[ -z "$OP" ]]; then
    echo '{"ok":false,"stderr":"broker_client.sh: missing op"}' >&2
    exit 1
fi

# The launcher passes the worktree path via the $AIRLOCK_WORKTREE env.
WORKTREE="${AIRLOCK_WORKTREE:-/workspace}"

REQ=$(printf '{"op":"%s","branch":"%s","worktree":"%s"}' "$OP" "$BRANCH" "$WORKTREE")

# Single-shot Unix-socket exchange. -q 0 closes our side after stdin EOF,
# letting the broker write its reply and close. -N is the BSD-nc spelling.
printf '%s\n' "$REQ" | nc -U -q 1 /broker.sock 2>/dev/null || \
    { echo '{"ok":false,"stderr":"broker socket not reachable"}' >&2; exit 1; }
