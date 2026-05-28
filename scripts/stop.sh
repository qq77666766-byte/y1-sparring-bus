#!/usr/bin/env bash
# Y1 Sparring Bus · 停止 server
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$HERE/sparring-center.pid"

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "✓ 已停止 PID $PID"
        rm -f "$PIDFILE"
    else
        echo "PID $PID 已经不存在，清理 pid 文件"
        rm -f "$PIDFILE"
    fi
else
    # fallback: 找 8765 端口的 LISTEN
    PID=$(lsof -iTCP:8765 -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill "$PID" && echo "✓ 已停止 PID $PID（通过端口找到）"
    else
        echo "未发现运行中的 server"
    fi
fi
