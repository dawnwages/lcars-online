# AGENTS.md

Guidance for AI coding agents (and people) changing this repository. For what the project is and how to run it, see [readme.md](readme.md).

## Setup and run

```bash
scripts/setup.sh                 # from a fresh clone; safe to rerun
scripts/start.sh                 # Prefect (4200), Django (8000), data schedule, LCARS (8080)
scripts/stop.sh
```

Python work happens in `wagtail/LCARSAPP/` with uv: `uv run python manage.py <command>`. Never use `pip` or the system Python. Frontend work happens in `LCARS/` with npm.

## Test before you finish

```bash
cd wagtail/LCARSAPP && uv run python manage.py test     # must pass; needs no model
cd wagtail/LCARSAPP && uv run python manage.py makemigrations --check --dry-run
cd LCARS && npm run build
```

Tests that exercise agents use PydanticAI's `TestModel` or `FunctionModel`; they must not need a model server or the network. Tests that write mission events from agent tools or validators use `TransactionTestCase` (PydanticAI runs sync tools and validators in worker threads).

## Layout

| Path | What |
|---|---|
| `wagtail/LCARSAPP/crew/science.py` | Deterministic statistics. The only place numbers are computed. |
| `wagtail/LCARSAPP/crew/agents.py` | PydanticAI agents, their tools, budgets, and the plan validator |
| `wagtail/LCARSAPP/crew/schemas.py` | Typed outputs each agent must produce |
| `wagtail/LCARSAPP/crew/flow.py` | The mission: a Prefect flow with approval gates |
| `wagtail/LCARSAPP/crew/ingest.py` | Scheduled NASA archive fetch (Prefect) |
| `wagtail/LCARSAPP/crew/runtime.py` | Starts and stops the model server and mission processes |
| `wagtail/LCARSAPP/missions/` | Mission log models, admin, JSON API, management commands |
| `wagtail/LCARSAPP/evals/` | DeepEval metrics graded from mission logs |
| `LCARS/src/pages/MissionLog.vue`, `LCARS/src/common/` | The bridge UI (missions, gates, launch) |
| `scripts/` | Setup, start/stop, model server, model downloads |

## Rules that must hold

- **Models never produce numbers.** Statistics live in `crew/science.py`; agents choose what to run and explain results.
- **Approvals are enforced in code, not prompts.** Don't add a path that skips a gate, publishes a report, or runs a plan without approval. Gate decisions record who decided and how.
- **The mission log is append-only.** Record with `MissionRecorder`; don't edit or delete events.
- **Tools are allow-listed per agent.** A new tool must log its call and result via `recorder.tool(...)`, and must return a clear error for bad input rather than a misleading result (an earlier tool returned 0 planets for a malformed filter and sent the model into a long loop).
- **Every agent run has a budget** (`STATION_LIMITS`, `CREW_MAX_TOKENS`, `CREW_REQUEST_TIMEOUT`). Keep runs bounded.
- **Data is reproducible.** Missions record the snapshot (and its SHA-256) they used. Don't change `crew/data/pscomppars-2026-10-07.csv`; tests use it as ground truth.
- **Local only.** The model server binds to 127.0.0.1 and requires `CREW_MODEL_KEY`. Bridge endpoints that change state require login, permission, and a CSRF token.

## Dependencies

Add top-level Python packages to `wagtail/LCARSAPP/requirements.in`, then:

```bash
uv pip compile requirements.in -o requirements.txt --universal --python-version 3.14
uv pip sync requirements.txt
```

`sqlalchemy<2.1` is pinned because Prefect 3.8's scheduler fails on SQLAlchemy 2.1. Telemetry for DeepEval, DeepTeam, and Prefect is turned off in settings; keep it off.

## Never commit

`wagtail/LCARSAPP/.env.local`, `db.sqlite3*`, `run/`, `backups/`, `media/`, `crew/data/snapshots/`, model files (`*.gguf`), `node_modules/`, `.venv/`. All are gitignored.
