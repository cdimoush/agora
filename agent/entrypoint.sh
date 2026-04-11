#!/bin/bash
set -e

# Install agora library in editable mode from mount
pip install -e ~ 2>&1 | tail -1
echo "[agora] Installed agora (editable) from ~"

# Initialize beads if not already present (no AGENTS.md, no pushing)
cd ~
if [ ! -d .beads ]; then
    bd init --skip-agents --skip-hooks --dolt-auto-commit=off --sandbox -q 2>/dev/null
    bd config set dolt.auto-push off >/dev/null 2>&1
    echo "[agora] Beads initialized"
else
    echo "[agora] Beads database found"
fi

# Run the agent
cd ~/agent
exec python agent.py
