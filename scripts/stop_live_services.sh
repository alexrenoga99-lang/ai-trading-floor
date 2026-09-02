#!/usr/bin/env bash
set -euo pipefail

pkill -f "streamlit run dashboard/app.py" >/dev/null 2>&1 || true
pkill -f "python live/worker.py" >/dev/null 2>&1 || true

echo "[live] Dashboard and worker stopped"
