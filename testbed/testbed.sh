#!/usr/bin/env bash
# Usage: ./testbed.sh on | off | status
set -euo pipefail

PIDFILE="/tmp/agora-testbed.pid"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGFILE="$REPO/logs/testbed.log"

case "${1:-status}" in
  on|start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Testbed already running (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    mkdir -p "$REPO/logs"
    nohup "$REPO/.venv/bin/python" "$REPO/testbed/run.py" \
      >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Testbed started (PID $!) — logs at $LOGFILE"
    ;;
  off|stop)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      kill "$(cat "$PIDFILE")"
      rm -f "$PIDFILE"
      echo "Testbed stopped"
    else
      echo "Testbed not running"
      rm -f "$PIDFILE"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Testbed running (PID $(cat "$PIDFILE"))"
    else
      echo "Testbed not running"
      rm -f "$PIDFILE"
    fi
    ;;
  *)
    echo "Usage: testbed.sh on|off|status"
    exit 1
    ;;
esac
