#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Quit any stale Streamlit processes before starting a fresh dashboard.
pkill -f "streamlit run dashboard/app.py" >/dev/null 2>&1 || true

# Load local env values when present.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PORT="${PORT:-8507}"

# Choose a free port if the preferred one is already used.
while :; do
  STATUS="$(python - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
    print("FREE")
except OSError:
    print("BUSY")
finally:
    sock.close()
PY
)"

  if [ "$STATUS" = "FREE" ]; then
    break
  fi
  PORT=$((PORT + 1))
done

echo "Starting dashboard on http://localhost:${PORT}"
exec python -m streamlit run dashboard/app.py --server.address 0.0.0.0 --server.port "$PORT"
