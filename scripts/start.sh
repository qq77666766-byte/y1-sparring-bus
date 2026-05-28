#!/usr/bin/env bash
# Y1 Sparring Bus · start local backend
# Usage: bash scripts/start.sh [port] [workspace-root]
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

PORT="${1:-8765}"
WORKSPACE_ARG="${2:-${SPARRING_WORKSPACE_ROOT:-}}"
HOST="127.0.0.1"
LOG="$HERE/sparring-center.log"
PIDFILE="$HERE/sparring-center.pid"
ARGS=(--host "$HOST" --port "$PORT")
if [ -n "$WORKSPACE_ARG" ]; then
    ARGS+=(--workspace-root "$WORKSPACE_ARG")
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "找不到 python3 / python3 not found"
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9+ required"
    exit 1
fi

mkdir -p "$HERE/jobs"

# 检查端口
if lsof -iTCP:$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    EXIST=$(lsof -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null)
    echo "端口 $PORT 已被进程 $EXIST 占用"
    echo "如果想停掉再起：bash scripts/stop.sh && bash scripts/start.sh"
    exit 1
fi

# 启动
nohup python3 "$HERE/tools/sparring_center.py" "${ARGS[@]}" \
    > "$LOG" 2>&1 &
PID=$!
disown 2>/dev/null || true
echo $PID > "$PIDFILE"

sleep 1.5
if kill -0 $PID 2>/dev/null; then
    echo "✓ Y1 Sparring Bus local backend started"
    echo "  PID:  $PID"
    echo "  URL:  http://$HOST:$PORT/sparring"
    echo "  LOG:  $LOG"
    if [ -n "$WORKSPACE_ARG" ]; then
        echo "  WORKSPACE: $WORKSPACE_ARG"
    fi
    echo ""
    echo "  Stop: bash scripts/stop.sh"

    # 尝试用浏览器自动打开
    if command -v open >/dev/null 2>&1; then
        open "http://$HOST:$PORT/sparring" 2>/dev/null || true
    fi
else
    echo "✗ 启动失败，看日志："
    tail -20 "$LOG"
    rm -f "$PIDFILE"
    exit 1
fi
