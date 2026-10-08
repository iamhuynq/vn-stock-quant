#!/usr/bin/env bash
# Local management UI on http://127.0.0.1:${UI_PORT:-8501} (this Mac only). Ctrl+C to stop.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run --group ui streamlit run src/stock_ui/app.py \
  --server.address 127.0.0.1 --server.port "${UI_PORT:-8501}" \
  --server.headless true --browser.gatherUsageStats false
