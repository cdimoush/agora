#!/bin/bash
set -e

# setup.sh — Build and run the Agora agent container.
#
# This script detects whether it's running in a git worktree and derives
# a unique container name from the worktree/repo directory basename.
# Each worktree gets its own container, enabling multiple agent personalities.
#
# Usage:
#   ./setup.sh          # Build and run
#   ./setup.sh build    # Build only
#   ./setup.sh stop     # Stop the container
#   ./setup.sh logs     # Tail container logs
#   ./setup.sh status   # Check if running

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect worktree vs main repo
if git rev-parse --is-inside-work-tree &>/dev/null; then
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    # Check if this is a worktree (git dir points elsewhere)
    GIT_DIR="$(git rev-parse --git-dir)"
    if [[ "$GIT_DIR" == *".git/worktrees/"* ]]; then
        # This is a worktree — use its basename
        BASENAME="$(basename "$REPO_ROOT")"
    else
        # This is the main repo — use its basename
        BASENAME="$(basename "$REPO_ROOT")"
    fi
else
    BASENAME="$(basename "$SCRIPT_DIR")"
fi

CONTAINER_NAME="agora-${BASENAME}"
IMAGE_NAME="agora-${BASENAME}:latest"

# Find the main git dir (for mounting .git and .beads)
MAIN_GIT_DIR="$(git rev-parse --git-common-dir 2>/dev/null || echo "$REPO_ROOT/.git")"
# Resolve to the parent of .git for the main repo path
MAIN_REPO="$(dirname "$MAIN_GIT_DIR")"
if [[ "$MAIN_GIT_DIR" == *"/.git" ]]; then
    MAIN_REPO="$(dirname "$MAIN_GIT_DIR")"
elif [[ "$MAIN_GIT_DIR" == *"/.git/"* ]]; then
    # worktree git dir is like /path/to/repo/.git/worktrees/name
    MAIN_REPO="$(echo "$MAIN_GIT_DIR" | sed 's|/\.git/worktrees/.*||')"
fi

# Paths
BD_BIN="${BD_BIN:-$(which bd 2>/dev/null || echo "$HOME/.local/bin/bd")}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
GH_CONFIG="${GH_CONFIG:-$HOME/.config/gh}"
ENV_FILE="${SCRIPT_DIR}/.env"

echo "[setup] Container: ${CONTAINER_NAME}"
echo "[setup] Image: ${IMAGE_NAME}"
echo "[setup] Repo root: ${REPO_ROOT}"
echo "[setup] Main repo: ${MAIN_REPO}"

cmd_build() {
    echo "[setup] Building ${IMAGE_NAME}..."

    # Stage the beads binary for Docker COPY
    if [ -f "$BD_BIN" ]; then
        cp "$BD_BIN" "${SCRIPT_DIR}/bd"
        echo "[setup] Copied beads CLI from ${BD_BIN}"
    else
        echo "[setup] WARNING: beads CLI not found at ${BD_BIN}"
        echo "[setup] Set BD_BIN=/path/to/bd or install beads first"
        exit 1
    fi

    docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"

    # Clean up staged binary
    rm -f "${SCRIPT_DIR}/bd"

    echo "[setup] Built ${IMAGE_NAME}"
}

cmd_run() {
    # Build first if image doesn't exist
    if ! docker image inspect "${IMAGE_NAME}" &>/dev/null; then
        cmd_build
    fi

    # Stop existing container if running
    if docker ps -q -f "name=${CONTAINER_NAME}" | grep -q .; then
        echo "[setup] Stopping existing ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" && docker rm "${CONTAINER_NAME}"
    elif docker ps -aq -f "name=${CONTAINER_NAME}" | grep -q .; then
        docker rm "${CONTAINER_NAME}"
    fi

    # Check for .env file
    ENV_ARGS=""
    if [ -f "$ENV_FILE" ]; then
        ENV_ARGS="--env-file ${ENV_FILE}"
    else
        echo "[setup] WARNING: No .env file found. Create one from .env.example"
        echo "[setup]   cp .env.example .env && edit .env"
    fi

    echo "[setup] Starting ${CONTAINER_NAME}..."
    docker run -d \
        --name "${CONTAINER_NAME}" \
        --restart unless-stopped \
        ${ENV_ARGS} \
        -e "BEADS_ACTOR=${BASENAME}" \
        -e "BD_DOLT_AUTO_PUSH=off" \
        -v "${CLAUDE_DIR}:/tmp/.claude-host:ro" \
        -v "${REPO_ROOT}:/workspace/agora:rw" \
        -v "${MAIN_REPO}/.git:${MAIN_REPO}/.git:rw" \
        -v "${MAIN_REPO}/.beads:${MAIN_REPO}/.beads:rw" \
        -v "${GH_CONFIG}:/home/agent/.config/gh:ro" \
        "${IMAGE_NAME}"

    echo "[setup] ${CONTAINER_NAME} is running"
    echo "[setup] Logs: ./setup.sh logs"
}

cmd_stop() {
    if docker ps -q -f "name=${CONTAINER_NAME}" | grep -q .; then
        echo "[setup] Stopping ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" && docker rm "${CONTAINER_NAME}"
        echo "[setup] Stopped"
    else
        echo "[setup] ${CONTAINER_NAME} is not running"
    fi
}

cmd_logs() {
    docker logs -f "${CONTAINER_NAME}" 2>&1
}

cmd_status() {
    if docker ps -q -f "name=${CONTAINER_NAME}" | grep -q .; then
        echo "${CONTAINER_NAME}: running"
        docker ps -f "name=${CONTAINER_NAME}" --format "  {{.Status}}"
    else
        echo "${CONTAINER_NAME}: stopped"
    fi
}

# Dispatch
case "${1:-run}" in
    build)  cmd_build ;;
    run)    cmd_run ;;
    stop)   cmd_stop ;;
    logs)   cmd_logs ;;
    status) cmd_status ;;
    *)
        echo "Usage: $0 {build|run|stop|logs|status}"
        exit 1
        ;;
esac
