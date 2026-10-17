#!/usr/bin/env bash
# Start LCARS Online: Prefect server, data schedule, Django, and the LCARS frontend.
#   scripts/start.sh
# Logs and PIDs go to wagtail/LCARSAPP/run/. Stop everything with scripts/stop.sh.
# The model server is started from the LCARS bridge when you launch a mission.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/wagtail/LCARSAPP"
RUN="$APP/run"
mkdir -p "$RUN"

[[ -f "$APP/.env.local" ]] || { echo "Run scripts/setup.sh first."; exit 1; }
set -a; source "$APP/.env.local"; set +a
export PREFECT_API_URL="${PREFECT_API_URL:-http://127.0.0.1:4200/api}"
export PYDANTIC_AI_NO_BANNER=1

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
wait_for() {  # url, name
  for _ in $(seq 1 60); do curl -sf -o /dev/null "$1" && { echo "✓ $2"; return; }; sleep 1; done
  echo "✗ $2 did not start; see $RUN"; exit 1
}
start() {  # name, port, dir, command...
  local name="$1" port="$2" dir="$3"; shift 3
  if port_busy "$port"; then
    echo "• $name: port $port is already in use; assuming it's running (scripts/stop.sh to restart)"
    return
  fi
  # Background only the service itself, so nothing keeps this script's output open
  (cd "$dir" || exit 1; nohup "$@" > "$RUN/$name.log" 2>&1 < /dev/null & echo $! > "$RUN/$name.pid")
}

# Keep the Mac awake while services run (macOS only)
if command -v caffeinate >/dev/null && ! [[ -f "$RUN/caffeinate.pid" && -n "$(ps -p "$(cat "$RUN/caffeinate.pid")" -o pid= 2>/dev/null)" ]]; then
  nohup caffeinate -is > /dev/null 2>&1 < /dev/null & echo $! > "$RUN/caffeinate.pid"
fi

start prefect-server 4200 "$APP" uv run prefect server start
wait_for http://127.0.0.1:4200/api/health "Prefect server   http://127.0.0.1:4200"

start django 8000 "$APP" uv run python manage.py runserver 8000
wait_for http://localhost:8000/api/crew/status/ "Django           http://localhost:8000/admin"

if pgrep -f "$APP/.venv/bin/python manage.py serve_ingest" >/dev/null; then
  echo "• Data schedule already running"
else
  (cd "$APP" || exit 1; nohup uv run python manage.py serve_ingest > "$RUN/serve-ingest.log" 2>&1 < /dev/null & echo $! > "$RUN/serve-ingest.pid")
  echo "✓ Data schedule    daily 06:00 America/New_York (log: run/serve-ingest.log)"
fi

start lcars 8080 "$REPO/LCARS" npm start
wait_for http://localhost:8080 "LCARS bridge     http://localhost:8080"

echo
echo "Log in at http://localhost:8000/admin as $ADMIN_USERNAME (password in wagtail/LCARSAPP/.env.local),"
echo "then open http://localhost:8080 → Missions → New mission."
