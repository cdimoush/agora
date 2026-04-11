#!/bin/bash
set -e

# agora.sh — Build and run the Agora agent container.
#
# This script detects whether it's running in a git worktree and derives
# a unique container name from the directory basename.
# Each worktree gets its own container, enabling multiple agent personalities.
#
# Usage:
#   bash agora.sh              # Build and run
#   bash agora.sh build        # Build only
#   bash agora.sh stop         # Stop the container
#   bash agora.sh logs         # Tail container logs
#   bash agora.sh status       # Check if running
#   bash agora.sh worktree <n> # Create a worktree at ../agora-<n>
#   bash agora.sh compose      # Start via docker-compose

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect worktree vs main repo
if git rev-parse --is-inside-work-tree &>/dev/null; then
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    BASENAME="$(basename "$REPO_ROOT")"
else
    BASENAME="$(basename "$SCRIPT_DIR")"
fi

CONTAINER_NAME="agora-${BASENAME}"
IMAGE_NAME="agora-${BASENAME}:latest"

# Find the main git dir (for worktree git operations)
MAIN_GIT_DIR="$(git rev-parse --git-common-dir 2>/dev/null || echo "$REPO_ROOT/.git")"
MAIN_REPO="$(dirname "$MAIN_GIT_DIR")"
if [[ "$MAIN_GIT_DIR" == *"/.git" ]]; then
    MAIN_REPO="$(dirname "$MAIN_GIT_DIR")"
elif [[ "$MAIN_GIT_DIR" == *"/.git/"* ]]; then
    MAIN_REPO="$(echo "$MAIN_GIT_DIR" | sed 's|/\.git/worktrees/.*||')"
fi

# Paths
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
GH_CONFIG="${GH_CONFIG:-$HOME/.config/gh}"
ENV_FILE="${SCRIPT_DIR}/agent/.env"
AGENT_DIR="${SCRIPT_DIR}/agent"

echo "[agora] Container: ${CONTAINER_NAME}"
echo "[agora] Image: ${IMAGE_NAME}"
echo "[agora] Repo root: ${REPO_ROOT}"

cmd_build() {
    echo "[agora] Building ${IMAGE_NAME}..."
    docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"
    echo "[agora] Built ${IMAGE_NAME}"
}

cmd_run() {
    # Build first if image doesn't exist
    if ! docker image inspect "${IMAGE_NAME}" &>/dev/null; then
        cmd_build
    fi

    # Stop existing container if running
    if docker ps -q -f "name=^/${CONTAINER_NAME}$" | grep -q .; then
        echo "[agora] Stopping existing ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" && docker rm "${CONTAINER_NAME}"
    elif docker ps -aq -f "name=^/${CONTAINER_NAME}$" | grep -q .; then
        docker rm "${CONTAINER_NAME}"
    fi

    # Check for .env file
    ENV_ARGS=""
    if [ -f "$ENV_FILE" ]; then
        ENV_ARGS="--env-file ${ENV_FILE}"
    else
        echo "[agora] WARNING: No .env file found at ${ENV_FILE}"
        echo "[agora]   cp agent/.env.example agent/.env && edit agent/.env"
    fi

    echo "[agora] Starting ${CONTAINER_NAME}..."
    docker run -d \
        --name "${CONTAINER_NAME}" \
        --restart unless-stopped \
        ${ENV_ARGS} \
        -e "BEADS_ACTOR=${BASENAME}" \
        -v "${CLAUDE_DIR}:/tmp/.claude-host:ro" \
        -v "${REPO_ROOT}:/workspace/agora:rw" \
        -v "${MAIN_REPO}/.git:${MAIN_REPO}/.git:rw" \
        -v "${GH_CONFIG}:/home/agent/.config/gh:ro" \
        "${IMAGE_NAME}"

    echo "[agora] ${CONTAINER_NAME} is running"
    echo "[agora] Logs: bash agora.sh logs"
}

cmd_stop() {
    if docker ps -q -f "name=^/${CONTAINER_NAME}$" | grep -q .; then
        echo "[agora] Stopping ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" && docker rm "${CONTAINER_NAME}"
        echo "[agora] Stopped"
    else
        echo "[agora] ${CONTAINER_NAME} is not running"
    fi
}

cmd_logs() {
    docker logs -f "${CONTAINER_NAME}" 2>&1
}

cmd_status() {
    if docker ps -q -f "name=^/${CONTAINER_NAME}$" | grep -q .; then
        echo "${CONTAINER_NAME}: running"
        docker ps -f "name=^/${CONTAINER_NAME}$" --format "  {{.Status}}"
    else
        echo "${CONTAINER_NAME}: stopped"
    fi
}

cmd_worktree() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: bash agora.sh worktree <name>"
        echo "Creates a worktree at ../agora-<name> on branch worktree/<name>"
        exit 1
    fi

    local wt_dir="${REPO_ROOT}/../agora-${name}"
    local branch="worktree/${name}"

    if [ -d "$wt_dir" ]; then
        echo "[agora] Worktree already exists: $wt_dir"
        exit 0
    fi

    # Try creating with new branch, fall back to existing branch
    if ! git worktree add "$wt_dir" -b "$branch" main 2>/dev/null; then
        git worktree add "$wt_dir" "$branch"
    fi

    echo "[agora] Created worktree at $wt_dir"
    echo "[agora] Branch: $branch"
    echo ""
    echo "Next steps:"
    echo "  cd $wt_dir"
    echo "  cp agent/.env.example agent/.env  # add your bot token"
    echo "  # edit agent/agent.yaml and agent/CLAUDE.md"
    echo "  bash agora.sh"
}

cmd_compose() {
    local action="${1:-up}"
    case "$action" in
        up)
            docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d --build
            ;;
        down)
            docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
            ;;
        *)
            docker compose -f "${SCRIPT_DIR}/docker-compose.yml" "$@"
            ;;
    esac
}

# Dispatch
case "${1:-run}" in
    build)     cmd_build ;;
    run)       cmd_run ;;
    stop)      cmd_stop ;;
    logs)      cmd_logs ;;
    status)    cmd_status ;;
    worktree)  cmd_worktree "$2" ;;
    compose)   shift; cmd_compose "$@" ;;
    *)
        echo "Usage: bash agora.sh {build|run|stop|logs|status|worktree|compose}"
        echo ""
        echo "Commands:"
        echo "  build              Build the Docker image"
        echo "  run                Build (if needed) and start the container"
        echo "  stop               Stop the container"
        echo "  logs               Tail container logs"
        echo "  status             Check container status"
        echo "  worktree <name>    Create a worktree at ../agora-<name>"
        echo "  compose [args]     Run docker-compose commands"
        exit 1
        ;;
esac
