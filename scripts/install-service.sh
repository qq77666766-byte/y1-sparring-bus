#!/usr/bin/env bash
# Install a user-level macOS LaunchAgent for the local backend.
# This is optional. It does not use sudo and only binds to 127.0.0.1.
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"
WORKSPACE_ROOT="${2:-${SPARRING_WORKSPACE_ROOT:-$HOME/Documents}}"
HOST="127.0.0.1"
LABEL="com.y1.sparring-bus"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/y1-sparring-bus"
PYTHON="$(command -v python3 || true)"

if [ -z "$PYTHON" ]; then
    echo "python3 not found. Install Python 3.9+ first."
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9+ required."
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$HERE/jobs"

python3 - "$PLIST" "$LABEL" "$PYTHON" "$HERE" "$HOST" "$PORT" "$WORKSPACE_ROOT" "$LOG_DIR" <<'PY'
import plistlib
import sys
from pathlib import Path

plist, label, python, root, host, port, workspace, log_dir = sys.argv[1:]
data = {
    "Label": label,
    "ProgramArguments": [
        python,
        str(Path(root) / "tools" / "sparring_center.py"),
        "--host", host,
        "--port", port,
        "--workspace-root", workspace,
    ],
    "WorkingDirectory": root,
    "RunAtLoad": True,
    "KeepAlive": False,
    "StandardOutPath": str(Path(log_dir) / "stdout.log"),
    "StandardErrorPath": str(Path(log_dir) / "stderr.log"),
}
with open(plist, "wb") as f:
    plistlib.dump(data, f, sort_keys=False)
PY

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

echo "✓ LaunchAgent installed"
echo "  Label:     $LABEL"
echo "  URL:       http://$HOST:$PORT/sparring"
echo "  Workspace: $WORKSPACE_ROOT"
echo "  Plist:     $PLIST"
echo "  Logs:      $LOG_DIR"
echo
echo "Status:      bash scripts/status.sh $PORT"
echo "Uninstall:   bash scripts/uninstall-service.sh"
