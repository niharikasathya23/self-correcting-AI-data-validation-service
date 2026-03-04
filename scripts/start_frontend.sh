#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

PORT="${PORT:-8501}"
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

export API_BASE_URL

echo "Starting Streamlit in stable mode on port $PORT"
echo "API_BASE_URL=$API_BASE_URL"

exec streamlit run frontend/app.py \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false
