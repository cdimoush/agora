#!/bin/bash
set -e

# agora.sh — Build and run the Agora agent container.
#
# Usage:
#   bash agora.sh              # Build and run
#   bash agora.sh build        # Build only
#   bash agora.sh stop         # Stop the container
#   bash agora.sh logs         # Tail container logs
#   bash agora.sh status       # Check if running

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASENAME="$(basename "$SCRIPT_DIR")"
CONTAINER_NAME="agora-${BASENAME}"
IMAGE_NAME="agora-${BASENAME}:latest"

BD_BIN="${BD_BIN:-$(which bd 2>/dev/null || echo "$HOME/.local/bin/bd")}"
GH_CONFIG="${GH_CONFIG:-$HOME/.config/gh}"
ENV_FILE="${SCRIPT_DIR}/agent/.env"

echo "[agora] Container: ${CONTAINER_NAME}"
echo "[agora] Image: ${IMAGE_NAME}"

cmd_build() {
    echo "[agora] Building ${IMAGE_NAME}..."

    # Stage the beads binary for Docker COPY
    if [ -f "$BD_BIN" ]; then
        cp "$BD_BIN" "${SCRIPT_DIR}/bd"
    else
        echo "[agora] ERROR: beads CLI not found at ${BD_BIN}"
        echo "[agora] Set BD_BIN=/path/to/bd or install beads first"
        exit 1
    fi

    docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"
    rm -f "${SCRIPT_DIR}/bd"
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
        -e "BD_DOLT_AUTO_PUSH=off" \
        -v "${SCRIPT_DIR}:/home/agent:rw" \
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

case "${1:-run}" in
    build)   cmd_build ;;
    run)     cmd_run ;;
    stop)    cmd_stop ;;
    logs)    cmd_logs ;;
    status)  cmd_status ;;
    *)
        echo "Usage: bash agora.sh {build|run|stop|logs|status}"
        exit 1
        ;;
esac
