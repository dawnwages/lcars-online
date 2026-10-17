#!/bin/sh
# Serve a local GGUF model on an OpenAI-compatible API for the crew.
#   scripts/model-server.sh ~/models/Qwen3.5-9B-Q4_K_M.gguf [thinking-budget]
# Port 8089 (Vite uses 8080). 16k context, all layers on the M1 GPU, one slot
# so memory stays predictable on a 16 GB machine. Thinking budget defaults to 0.
# Requires an API key (CREW_MODEL_KEY) so web pages in the browser cannot use it.
set -e
ENV_LOCAL="$(cd "$(dirname "$0")/.." && pwd)/wagtail/LCARSAPP/.env.local"
if [ -z "${CREW_MODEL_KEY:-}" ] && [ -f "$ENV_LOCAL" ]; then
  CREW_MODEL_KEY=$(grep '^CREW_MODEL_KEY=' "$ENV_LOCAL" | cut -d= -f2-)
fi
MODEL="${1:?path to a .gguf model}"
BUDGET="${2:-0}"
exec llama-server -m "$MODEL" --alias "$(basename "$MODEL" .gguf)" \
  --port 8089 --host 127.0.0.1 -c 16384 -ngl 99 -fa on -np 1 \
  --api-key "${CREW_MODEL_KEY:-lcars-local}" \
  --jinja --reasoning-budget "$BUDGET" --temp 0.2 --seed 0 --metrics
