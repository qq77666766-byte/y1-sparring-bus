#!/usr/bin/env bash
# Show local backend and optional LaunchAgent status.
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$HERE/sparring-center.pid"
PORT="${1:-8765}"
HOST="127.0.0.1"
LABEL="com.y1.sparring-bus"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "=== Y1 Sparring Bus · status / 状态 ==="

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "PID file: running ($PID)"
    else
        echo "PID file: stale ($PID)"
    fi
else
    echo "PID file: none"
fi

PORT_PID=$(lsof -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "Port $PORT: listening (PID $PORT_PID)"
else
    echo "Port $PORT: not listening"
fi

python3 - "$HOST" "$PORT" <<'PY' || true
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print("Health: reachable")
    print("Workspace:", data.get("workspace"))
    print("Auto mode:", "available" if data.get("auto_mode_available") else "manual handoff")
except Exception as exc:  # noqa: BLE001
    print(f"Health: not reachable ({exc})")
PY

if [ -f "$PLIST" ]; then
    echo "LaunchAgent: installed ($PLIST)"
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
        && echo "LaunchAgent state: loaded" \
        || echo "LaunchAgent state: not loaded"
else
    echo "LaunchAgent: not installed"
fi
