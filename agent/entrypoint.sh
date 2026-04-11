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

# Install agora library in editable mode from mount
pip install -e ~/agora 2>&1 | tail -1
echo "[agora] Installed agora (editable) from ~/agora"

# Run the agent
cd ~/agora/agent
exec python agent.py
