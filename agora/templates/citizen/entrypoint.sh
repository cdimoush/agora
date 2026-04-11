#!/bin/bash
set -e

# Copy Claude credentials from read-only staging mount into writable .claude dir
if [ -f /tmp/.claude-host/.credentials.json ]; then
    cp /tmp/.claude-host/.credentials.json /home/agent/.claude/.credentials.json
    echo "[agora] Claude credentials loaded"
fi
if [ -f /tmp/.claude-host/settings.json ]; then
    cp /tmp/.claude-host/settings.json /home/agent/.claude/settings.json
fi

if [ -f /workspace/agora/pyproject.toml ]; then
    echo "[agora] Worktree detected, installing editable agora..."
    pip install -e /workspace/agora 2>&1 | tail -1
    echo "[agora] Using editable agora from /workspace/agora"
else
    echo "[agora] No worktree mounted, using installed agora"
fi

exec python agent.py
