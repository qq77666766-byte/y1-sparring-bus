#!/usr/bin/env bash
# Y1 Sparring Bus · local install helper
# This does not install Claude/Codex or start a persistent service.
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

echo "=== Y1 Sparring Bus · install / 安装 ==="
echo "Root: $HERE"
echo

if [ "$(uname -s)" != "Darwin" ]; then
    warn "v1 is tested for macOS. Other systems may need manual adjustment."
else
    pass "macOS detected"
fi

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found. Install Python 3.9+ first."
fi

PY=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    pass "Python $PY"
else
    fail "Python $PY is too old. Need Python 3.9+."
fi

mkdir -p "$HERE/jobs"
pass "jobs/ directory ready"

chmod +x "$HERE"/scripts/*.sh 2>/dev/null || warn "Could not chmod scripts; use bash scripts/<name>.sh if needed."
pass "scripts ready"

echo
bash "$HERE/scripts/doctor.sh"

echo
cat <<EOF
Next steps / 下一步：

1. Start the local backend:
   bash scripts/start.sh

2. Open:
   http://127.0.0.1:8765/sparring

3. Check full automatic mode:
   bash scripts/doctor.sh --strict

4. Run a backend smoke test without Claude/Codex:
   bash scripts/smoke-test.sh

Optional login-time background service:
   bash scripts/install-service.sh 8765 ~/Documents
EOF
