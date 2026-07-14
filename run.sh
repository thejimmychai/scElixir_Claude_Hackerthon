#!/usr/bin/env bash
# Launch the Universal Developmental Reprogramming Pipeline (API + UI).
# Zero dependencies — needs only a Python 3.8+ interpreter.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${REPRO_PORT:-8765}"
echo "Starting on http://127.0.0.1:${PORT}/  (Ctrl-C to stop)"
exec python3 -m backend.app --port "${PORT}"
