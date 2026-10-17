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

# Anything from this checkout that outlived its parent. Every pattern is scoped to this
# checkout's paths (or the crew's model port) so other projects' servers are untouched;
# `uv run` wrappers exit on their own when their Python child stops.
PATTERNS=(
  "$REPO/wagtail/LCARSAPP/.venv/bin/python.* manage.py (runserver|serve_ingest|run_mission|bakeoff|red_team)"
  "$REPO/wagtail/LCARSAPP/.venv/bin/.*prefect server start"
  "$REPO/LCARS/node_modules/.bin/vite"
  "$REPO/scripts/model-server.sh"
  "llama-server .*--port 8089"
)
for p in "${PATTERNS[@]}"; do pkill -TERM -f "$p" 2>/dev/null; done

# Some (Prefect's serve loop) ignore a polite stop; give them a moment, then insist
for _ in 1 2 3 4 5; do
  alive=0
  for p in "${PATTERNS[@]}"; do pgrep -f "$p" >/dev/null && alive=1; done
  (( alive )) || break
  sleep 1
done
for p in "${PATTERNS[@]}"; do pkill -KILL -f "$p" 2>/dev/null; done
echo "Done."
