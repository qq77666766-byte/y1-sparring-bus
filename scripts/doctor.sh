#!/usr/bin/env bash
# Y1 Sparring Bus · local readiness check
# Default mode checks whether the local UI/backend can run.
# Use --strict to require the full automatic Claude + Codex loop.
set -e

STRICT=0
if [ "${1:-}" = "--strict" ]; then
    STRICT=1
elif [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    cat <<'EOF'
Usage:
  bash scripts/doctor.sh           # basic local server readiness
  bash scripts/doctor.sh --strict  # full automatic Claude/Codex readiness

Default mode:
  - Python and port checks are blocking.
  - Claude/Codex are warnings, because the UI and manual handoff still work.

Strict mode:
  - Claude CLI, Codex CLI, and Codex login are required.
EOF
    exit 0
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok=0; warn=0; fail=0
pass() { echo -e "${GREEN}✓${NC} $1"; ok=$((ok+1)); }
warning() { echo -e "${YELLOW}⚠${NC} $1"; warn=$((warn+1)); }
err() { echo -e "${RED}✗${NC} $1"; fail=$((fail+1)); }
need_auto() {
    if [ "$STRICT" -eq 1 ]; then
        err "$1"
    else
        warning "$1（完整自动互搏需要；本机页面和手动接力仍可用）"
    fi
}

echo "=== Y1 Sparring Bus · 环境体检 / Readiness check ==="
if [ "$STRICT" -eq 1 ]; then
    echo "Mode: strict full-auto check"
else
    echo "Mode: basic local server check"
fi
echo

# Python 3.9+
if command -v python3 >/dev/null 2>&1; then
    PY=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        pass "Python $PY"
    else
        err "Python $PY 太老，需 >= 3.9"
    fi
else
    err "找不到 python3 / python3 not found"
fi

# Claude CLI
if command -v claude >/dev/null 2>&1; then
    CV=$(claude --version 2>&1 | head -1)
    pass "Claude CLI: $CV"
else
    need_auto "找不到 claude / Claude Code CLI not found"
fi

# Codex CLI
CODEX=""
if command -v codex >/dev/null 2>&1; then
    CODEX=$(command -v codex)
elif [ -x "/Applications/Codex.app/Contents/Resources/codex" ]; then
    CODEX="/Applications/Codex.app/Contents/Resources/codex"
fi
if [ -n "$CODEX" ]; then
    CV=$($CODEX --version 2>&1 | head -1)
    pass "Codex CLI: $CV ($CODEX)"
else
    need_auto "找不到 Codex CLI / Codex CLI not found"
fi

# Codex 登录凭证
if [ -f ~/.codex/auth.json ]; then
    pass "Codex 已登录（~/.codex/auth.json 存在）"
else
    need_auto "Codex 未登录 / Codex auth missing: run codex login"
fi

# ANTHROPIC_API_KEY 警告（可继续，但提醒）
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    warning "Shell 里有 ANTHROPIC_API_KEY。代码会自动 strip，但建议 unset。"
fi

# Script execute bits are useful when cloned from git.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$HERE/scripts/start.sh" ] && [ -x "$HERE/scripts/stop.sh" ]; then
    pass "scripts are executable"
else
    warning "scripts 可能没有执行权限；可先跑：chmod +x scripts/*.sh，或用 bash scripts/start.sh"
fi

# 端口 8765
if lsof -iTCP:8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
    PID=$(lsof -iTCP:8765 -sTCP:LISTEN -t 2>/dev/null)
    warning "8765 端口已被进程 $PID 占用（如果是 sparring server，没事；否则改端口）"
else
    pass "端口 8765 空闲"
fi

echo
echo "=== 体检结果：${ok} 通过 / ${warn} 警告 / ${fail} 失败 ==="
if [ $fail -gt 0 ]; then
    echo "请先修复失败项。"
    exit 1
else
    if [ "$STRICT" -eq 1 ] && [ "$warn" -eq 0 ]; then
        echo "完整自动互搏已就绪：bash scripts/start.sh"
    elif [ "$STRICT" -eq 1 ]; then
        echo "完整自动互搏依赖已通过；上面的警告项请按需处理。"
    else
        echo "本机页面可以启动：bash scripts/start.sh"
        echo "完整自动互搏检查：bash scripts/doctor.sh --strict"
    fi
fi
