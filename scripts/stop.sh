#!/usr/bin/env bash
# Stop everything scripts/start.sh started, plus any model server and running mission.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$REPO/wagtail/LCARSAPP/run"

stop_pid() {  # name
  local f="$RUN/$1.pid"
  [[ -f "$f" ]] || return 0
  local pid; pid=$(cat "$f")
  if kill -0 "$pid" 2>/dev/null; then
    pkill -TERM -P "$pid" 2>/dev/null   # children (uv runs Python as a child)
    kill -TERM "$pid" 2>/dev/null && echo "✓ stopped $1"
  fi
  rm -f "$f"
}

for name in lcars serve-ingest django prefect-server model-server mission caffeinate; do
  stop_pid "$name"
done

# Anything from this checkout that outlived its parent
pkill -f "$REPO/wagtail/LCARSAPP/.venv/bin/python.* manage.py (runserver|serve_ingest|run_mission|bakeoff|red_team)" 2>/dev/null
pkill -f "$REPO/wagtail/LCARSAPP/.venv/bin/.*prefect server start" 2>/dev/null
pkill -f "$REPO/LCARS/node_modules/.bin/vite" 2>/dev/null
pkill -f "$REPO/scripts/model-server.sh" 2>/dev/null
pkill -f "llama-server .*--port 8089" 2>/dev/null
echo "Done."
