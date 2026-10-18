#!/usr/bin/env bash
# InferForge — AMD Inference Optimization Platform
set -euo pipefail

UVICORN_PID=""

_shutdown() {
  echo ""
  echo "  [inferforge] Shutting down..."
  if [ -n "$UVICORN_PID" ]; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
  echo "  [inferforge] Stopped."
  exit 0
}
trap _shutdown INT TERM TSTP HUP EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${INFERFORGE_HOST:-0.0.0.0}"
PORT="${INFERFORGE_PORT:-7801}"

echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║       InferForge — AMD Inference Optimization        ║"
echo "  ║       Unified Planning + Kernel Optimization         ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo ""

# Auto-install dependencies if missing
python3 -c "import fastapi" 2>/dev/null || { echo "  [setup] Installing fastapi..."; pip3 install fastapi --break-system-packages -q; }
python3 -c "import anthropic" 2>/dev/null || { echo "  [setup] Installing anthropic..."; pip3 install anthropic --break-system-packages -q; }
python3 -c "import uvicorn" 2>/dev/null || { echo "  [setup] Installing uvicorn[standard]..."; pip3 install "uvicorn[standard]" --break-system-packages -q; }
python3 -c "import dotenv" 2>/dev/null || { echo "  [setup] Installing python-dotenv..."; pip3 install python-dotenv --break-system-packages -q; }
python3 -c "import httpx" 2>/dev/null || { echo "  [setup] Installing httpx..."; pip3 install httpx --break-system-packages -q; }
python3 -c "import pydantic" 2>/dev/null || { echo "  [setup] Installing pydantic..."; pip3 install pydantic --break-system-packages -q; }
python3 -c "import jinja2" 2>/dev/null || { echo "  [setup] Installing jinja2..."; pip3 install jinja2 --break-system-packages -q; }
python3 -c "import aiofiles" 2>/dev/null || { echo "  [setup] Installing aiofiles..."; pip3 install aiofiles --break-system-packages -q; }
python3 -c "import multipart" 2>/dev/null || { echo "  [setup] Installing python-multipart..."; pip3 install python-multipart --break-system-packages -q; }
python3 -c "import bcrypt" 2>/dev/null || { echo "  [setup] Installing bcrypt..."; pip3 install bcrypt --break-system-packages -q; }
python3 -c "import jwt" 2>/dev/null || { echo "  [setup] Installing pyjwt..."; pip3 install pyjwt --break-system-packages -q; }

# Load .env if present (makes all vars available to uvicorn and subprocesses)
cd "$SCRIPT_DIR"
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  echo "  Env:      .env loaded"
else
  echo "  Env:      no .env file found (using shell environment)"
fi

# Check API credentials
python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from inferforge.config import is_api_configured, is_api_connected, CREDENTIAL_SOURCE, API_CONNECTION
    if not is_api_configured():
        print('  API:      not configured')
        print('  Set ANTHROPIC_API_KEY or AMD_GATEWAY_KEY in .env or environment')
    elif is_api_connected():
        print(f'  API:      connected ({CREDENTIAL_SOURCE})')
    else:
        print(f'  API:      credentials found ({CREDENTIAL_SOURCE}) but connection not verified')
except Exception as e:
    print(f'  API:      check skipped ({e})')
print()
" 2>/dev/null || true

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo "  Project:  ${SCRIPT_DIR}"
echo "  URL:      http://${IP}:${PORT}"
echo "  Local:    http://localhost:${PORT}"
echo ""
echo "  Routes:"
echo "    /       Classic  (evolved 3-panel layout)"
echo "    /nova   Nova     (DevOps dashboard)"
echo "    /era    Era      (Mission Control)"
echo ""

if [ -n "${INFERFORGE_AUTH_USER:-}" ]; then
    echo "  Auth:     enabled (user: ${INFERFORGE_AUTH_USER})"
else
    echo "  Auth:     disabled"
fi
echo ""

# Clean Python bytecache
find "$SCRIPT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
echo "  Cache:    cleaned"

# Kill stale process on port
STALE_PID=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
  echo "  Port:     $PORT in use by PID $STALE_PID — killing..."
  kill "$STALE_PID" 2>/dev/null || true
  sleep 1
  kill -9 "$STALE_PID" 2>/dev/null || true
  echo "  Port:     $PORT released"
else
  echo "  Port:     $PORT available"
fi
echo ""

python3 -m uvicorn inferforge.server:app --host "$HOST" --port "$PORT" --log-level warning &
UVICORN_PID=$!
wait "$UVICORN_PID"
