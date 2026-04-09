#!/bin/bash
set -e

if [ -f /workspace/agora/pyproject.toml ]; then
    echo "[agora] Worktree detected, installing editable agora..."
    pip install -e /workspace/agora 2>&1 | tail -1
    echo "[agora] Using editable agora from /workspace/agora"
else
    echo "[agora] No worktree mounted, using installed agora"
fi

exec python agent.py
