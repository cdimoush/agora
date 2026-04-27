#!/usr/bin/env bash
# run.sh — entry point for the agent-airlock-toy.
# Validates prerequisites, builds images on first run, hands off to launcher.py.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# --- usage ------------------------------------------------------------------

usage() {
    cat <<'EOF'
Usage: ./run.sh <repo-path> "<task description>"

Example:
  ./run.sh ./examples/broken_calc "fix the failing test in test_calc.py"

Prerequisites (checked below):
  - Docker is installed and the daemon is running.
  - ANTHROPIC_API_KEY is set (or in a .env file beside this script).
  - You have at least one SSH key loaded in ssh-agent (for git push via the broker).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
    usage
    exit 1
fi

REPO_PATH="$1"
TASK="$2"

# --- load .env if present ----------------------------------------------------

if [[ -f "$HERE/.env" ]]; then
    # shellcheck disable=SC1091
    set -a; . "$HERE/.env"; set +a
fi

# --- prerequisite checks -----------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not installed. Install Docker Desktop or OrbStack." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker daemon is not reachable. Start Docker first." >&2
    exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set. Put it in .env or export it." >&2
    exit 1
fi

if ! ssh-add -l >/dev/null 2>&1; then
    echo "WARN: ssh-agent has no keys. 'broker_client.sh git_push ...' will fail." >&2
    echo "      Run: ssh-add ~/.ssh/id_ed25519  (or your key)" >&2
fi

# --- build images on first run ----------------------------------------------

if ! docker image inspect airlock-code:latest >/dev/null 2>&1; then
    echo "[run.sh] building airlock-code image (first run)..."
    docker build -t airlock-code:latest -f Dockerfile.code .
fi

if ! docker image inspect airlock-agent:latest >/dev/null 2>&1; then
    echo "[run.sh] building airlock-agent image (first run)..."
    docker build -t airlock-agent:latest -f Dockerfile.agent .
fi

# --- launch ------------------------------------------------------------------

exec python3 launcher.py "$REPO_PATH" "$TASK"
