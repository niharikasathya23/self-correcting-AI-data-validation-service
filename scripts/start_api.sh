#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1
export LLM_CONCURRENCY="${LLM_CONCURRENCY:-10}"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "Starting API in stable mode (no --reload)"
echo "HOST=$HOST PORT=$PORT WORKERS=$WORKERS LLM_CONCURRENCY=$LLM_CONCURRENCY"

exec uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --timeout-keep-alive 30 \
  --no-server-header
