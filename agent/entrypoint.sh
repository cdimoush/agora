#!/bin/bash
set -e

# Copy Claude credentials from read-only staging mount
if [ -f /tmp/.claude-host/.credentials.json ]; then
    cp /tmp/.claude-host/.credentials.json /home/agent/.claude/.credentials.json
    echo "[agora] Claude credentials loaded"
fi
if [ -f /tmp/.claude-host/settings.json ]; then
    cp /tmp/.claude-host/settings.json /home/agent/.claude/settings.json
fi

# If worktree is mounted, install agora as editable
if [ -f /workspace/agora/pyproject.toml ]; then
    echo "[agora] Worktree detected, installing editable agora..."
    pip install -e /workspace/agora 2>&1 | tail -1
    echo "[agora] Using editable agora from /workspace/agora"

    cd /workspace/agora
    BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
    echo "[agora] Working on branch: $BRANCH"

    # Read agent name from config
    AGENT_NAME=$(python -c "import yaml; print(yaml.safe_load(open('/agent/agent.yaml'))['name'])" 2>/dev/null || echo "dev")

    # Install pre-push hook: enforce namespace branches
    HOOKS_DIR="$(git rev-parse --git-dir)/hooks"
    mkdir -p "$HOOKS_DIR"
    cat > "$HOOKS_DIR/pre-push" << 'HOOK'
#!/bin/bash
AGENT_NAME="__AGENT_NAME__"

while read local_ref local_sha remote_ref remote_sha; do
    branch="${remote_ref#refs/heads/}"
    if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
        echo "[agora] BLOCKED: ${AGENT_NAME} cannot push directly to ${branch}"
        echo "[agora] Push to ${AGENT_NAME}/<branch-name> instead"
        exit 1
    fi
    if [[ "$branch" != "${AGENT_NAME}/"* ]]; then
        echo "[agora] BLOCKED: ${AGENT_NAME} can only push to ${AGENT_NAME}/* branches"
        echo "[agora] Got: ${branch}"
        exit 1
    fi
done
HOOK
    sed -i "s/__AGENT_NAME__/$AGENT_NAME/g" "$HOOKS_DIR/pre-push"
    chmod +x "$HOOKS_DIR/pre-push"
    echo "[agora] Push guard installed: ${AGENT_NAME}/* branches only"

    cd /agent
else
    echo "[agora] No worktree mounted, using installed agora"
fi

exec python agent.py
