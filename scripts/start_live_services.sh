#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

LOG_DIR="$ROOT_DIR/.logs"
mkdir -p "$LOG_DIR"

start_dashboard() {
  if pgrep -f "streamlit run dashboard/app.py" >/dev/null 2>&1; then
    echo "[live] Dashboard already running"
    return
  fi

  nohup bash ./scripts/run_dashboard.sh >"$LOG_DIR/dashboard.log" 2>&1 &
  echo "[live] Dashboard started in background"
}

start_worker() {
  local timeframe="${WATCHER_TIMEFRAME:-1m}"
  local interval="${WATCHER_INTERVAL_SECONDS:-15}"

  if pgrep -f "python live/worker.py" >/dev/null 2>&1; then
    echo "[live] Worker already running"
    return
  fi

  nohup env \
    WATCHER_TIMEFRAME="$timeframe" \
    WATCHER_INTERVAL_SECONDS="$interval" \
    python live/worker.py --timeframe "$timeframe" --interval "$interval" \
    >"$LOG_DIR/worker.log" 2>&1 &

  echo "[live] Worker started in background"
}

start_dashboard
start_worker

echo "[live] Services active. Logs: $LOG_DIR"
