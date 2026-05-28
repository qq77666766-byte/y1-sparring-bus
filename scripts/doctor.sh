#!/usr/bin/env bash
# Y1 Sparring Bus · 环境体检
# 检查本机是否齐了 Claude CLI / Codex CLI / Python，账号是否登录
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok=0; warn=0; fail=0
pass() { echo -e "${GREEN}✓${NC} $1"; ok=$((ok+1)); }
warning() { echo -e "${YELLOW}⚠${NC} $1"; warn=$((warn+1)); }
err() { echo -e "${RED}✗${NC} $1"; fail=$((fail+1)); }

echo "=== Y1 Sparring Bus · 环境体检 ==="
echo

# Python 3.9+
if command -v python3 >/dev/null 2>&1; then
    PY=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo $PY | cut -d. -f1)
    PY_MINOR=$(echo $PY | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
        pass "Python $PY"
    else
        err "Python $PY 太老，需 ≥ 3.9"
    fi
else
    err "找不到 python3"
fi

# Claude CLI
if command -v claude >/dev/null 2>&1; then
    CV=$(claude --version 2>&1 | head -1)
    pass "Claude CLI: $CV"
else
    err "找不到 claude（装 Claude Code CLI: npm install -g @anthropic-ai/claude-code）"
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
    err "找不到 Codex CLI（装 Codex.app）"
fi

# Codex 登录凭证
if [ -f ~/.codex/auth.json ]; then
    pass "Codex 已登录（~/.codex/auth.json 存在）"
else
    err "Codex 未登录：跑 codex login"
fi

# ANTHROPIC_API_KEY 警告（可继续，但提醒）
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    warning "Shell 里有 ANTHROPIC_API_KEY 环境变量。代码会自动 strip，不影响计费安全，但建议 unset。"
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
    echo "请先修复失败项再启动 server。"
    exit 1
else
    echo "可以启动了：./scripts/start.sh"
fi
