#!/usr/bin/env bash
# Start a temporary local server and verify core HTTP endpoints.
# This test does not require Claude or Codex login.
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8876}"
HOST="127.0.0.1"
LOG="$HERE/smoke-test.log"
PID=""

cleanup() {
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Port $PORT is busy. Try another port: bash scripts/smoke-test.sh 8877"
    exit 1
fi

python3 "$HERE/tools/sparring_center.py" \
    --host "$HOST" \
    --port "$PORT" \
    --workspace-root "$HERE/examples" \
    > "$LOG" 2>&1 &
PID=$!

python3 - "$HOST" "$PORT" "$HERE/examples/demo_proposal_zh.md" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

host, port, sample = sys.argv[1], sys.argv[2], sys.argv[3]
base = f"http://{host}:{port}"

def get(path):
    with urllib.request.urlopen(base + path, timeout=3) as resp:
        return resp.read().decode("utf-8")

def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))

deadline = time.time() + 8
last_error = None
while time.time() < deadline:
    try:
        health = json.loads(get("/api/health"))
        page = get("/sparring")
        preflight = post("/api/preflight", {
            "source_path": sample,
            "goal": "Smoke test only. Do not modify files.",
        })
        if "Y1 Sparring Bus" not in page:
            raise RuntimeError("/sparring page did not contain expected title")
        if not preflight.get("ok"):
            raise RuntimeError(f"preflight failed: {preflight}")
        print("✓ server health:", health.get("auto_mode_note", "ok"))
        print("✓ /sparring page loaded")
        print("✓ preflight accepted demo file")
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        time.sleep(0.4)

raise SystemExit(f"Smoke test failed: {last_error}")
PY

echo "✓ smoke test passed"
