#!/usr/bin/env bash
# Set up LCARS Online from a fresh clone. Safe to run again.
#   scripts/setup.sh            # everything except model downloads
#   scripts/setup.sh --offline  # skip fetching today's NASA data (uses the pinned baseline)
# Then: scripts/download-models.sh, scripts/start.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/wagtail/LCARSAPP"
OFFLINE=0
[[ "${1:-}" == "--offline" ]] && OFFLINE=1

say()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '   \033[31m✗ %s\033[0m\n' "$*"; exit 1; }

say "Checking prerequisites"
command -v git >/dev/null || die "git is missing. macOS: xcode-select --install"
ok "git"
command -v uv >/dev/null || die "uv is missing. Install: curl -LsSf https://astral.sh/uv/install.sh | sh  (or: brew install uv)"
ok "uv $(uv --version | awk '{print $2}')"
command -v node >/dev/null || die "Node.js is missing. Install Node 22 LTS or newer: brew install node  (or https://nodejs.org)"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
NODE_MINOR=$(node -p 'process.versions.node.split(".")[1]')
if (( NODE_MAJOR < 20 )) || (( NODE_MAJOR == 20 && NODE_MINOR < 19 )) || (( NODE_MAJOR == 21 )) || (( NODE_MAJOR == 22 && NODE_MINOR < 12 )); then
  die "Node $(node --version) is too old for Vite 8; need 20.19+ or 22.12+"
fi
ok "node $(node --version)"
if command -v llama-server >/dev/null || [[ -x /opt/homebrew/bin/llama-server ]] || [[ -x /usr/local/bin/llama-server ]]; then
  ok "llama-server (llama.cpp)"
else
  warn "llama-server not found. Real-model missions need it: brew install llama.cpp"
  warn "Everything else (and the test model) works without it."
fi

say "Backend: Python, packages, database"
cd "$APP"
uv python install            # the version pinned in .python-version
[[ -d .venv ]] || uv venv -q
uv pip sync -q requirements.txt
ok "Python $(uv run python -c 'import platform; print(platform.python_version())') and $(grep -c '==' requirements.txt) pinned packages"

if [[ ! -f .env.local ]]; then
  gen() { uv run python -c 'import secrets; print(secrets.token_urlsafe(24))'; }
  cat > .env.local <<EOF
# Local secrets for this machine (gitignored). Created by scripts/setup.sh.
# Admin login for http://localhost:8000/admin
ADMIN_USERNAME=captain
ADMIN_PASSWORD=$(gen)
# Key the local model server requires; the crew sends it automatically
CREW_MODEL_KEY=$(gen)
EOF
  chmod 600 .env.local
  ok "Created .env.local with a generated admin password and model key"
else
  ok ".env.local already exists (kept)"
fi
set -a; source .env.local; set +a

uv run python manage.py migrate -v0
ok "Database migrated"
if uv run python manage.py shell -c "from django.contrib.auth import get_user_model as U; import sys; sys.exit(0 if U().objects.filter(username='$ADMIN_USERNAME').exists() else 1)" 2>/dev/null; then
  ok "Admin user '$ADMIN_USERNAME' already exists"
else
  DJANGO_SUPERUSER_PASSWORD="$ADMIN_PASSWORD" uv run python manage.py createsuperuser \
    --noinput --username "$ADMIN_USERNAME" --email "$ADMIN_USERNAME@example.com" >/dev/null
  ok "Created admin user '$ADMIN_USERNAME' (password in wagtail/LCARSAPP/.env.local)"
fi

if (( OFFLINE )); then
  warn "Skipping NASA fetch (--offline); missions use the pinned 2026-10-07 baseline"
elif uv run python manage.py ingest_archive >/dev/null 2>&1; then
  ok "Fetched today's NASA Exoplanet Archive: $(uv run python manage.py shell -c 'from missions.models import Snapshot; print(Snapshot.latest_usable())' 2>/dev/null | tail -1)"
else
  warn "Could not reach the NASA archive; missions use the pinned baseline. Retry: uv run python manage.py ingest_archive"
fi

say "Frontend: LCARS (Vue + Vite)"
cd "$REPO/LCARS"
npm ci --no-fund --no-audit --loglevel=error
ok "Frontend packages installed"

say "Done"
MODELS_DIR="${CREW_MODELS_DIR:-$HOME/models}"
if ls "$MODELS_DIR"/*.gguf >/dev/null 2>&1; then
  ok "Models found in $MODELS_DIR: $(ls "$MODELS_DIR"/*.gguf | xargs -n1 basename | tr '\n' ' ')"
else
  warn "No models in $MODELS_DIR yet. Download one (5.7 GB): scripts/download-models.sh qwen"
fi
cat <<EOF

   Next:
     scripts/download-models.sh qwen   # once; a local model for real missions
     scripts/start.sh                  # start everything
   Then open http://localhost:8080 and log in at http://localhost:8000/admin
   as '$ADMIN_USERNAME' (password in wagtail/LCARSAPP/.env.local).
EOF
