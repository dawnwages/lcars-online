# LCARS Online

<img src="UnitedFederationofPlanets.png" alt="United Federation of Planets Logo" height="100" max-width="200"/><img src="Vue.js_Logo.png" alt="Vue JS Logo" height="100" max-width="200"/><img src="wagtail-logo.png" alt="Wagtail Logo" height="100" maxwidth="200"/>

**What if your data science dashboard looked like the bridge of the Enterprise, and actually worked like it too?**

LCARS Online is a Star Trek LCARS interface on top of a crew of AI agents that analyze real NASA data. The agents plan and review; deterministic Python computes every number; a person approves each decision. Everything runs locally on a laptop, including the language model.

This is the companion repo for **[To Boldly Go: Data Science Exploration with AI Agents (ft Star Trek's LCARS theme)](https://2026.allthingsopen.org/sessions/to-boldly-go-data-science-exploration-with-ai-agents-ft-star-treks-lcars-theme)** at All Things Open 2026, Raleigh, NC.

## Quick start (from zero)

Tested on an Apple Silicon Mac with 16 GB of memory. Linux should work; see [Other platforms](#other-platforms).

**1. Install the prerequisites** (once per machine):

```bash
xcode-select --install          # git (skip if you have it)
brew install uv node llama.cpp  # uv (Python), Node.js 22+, llama.cpp (local model server)
```

No Homebrew? Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`, Node.js from [nodejs.org](https://nodejs.org), and llama.cpp from [its releases](https://github.com/ggml-org/llama.cpp/releases).

**2. Get the code and set it up:**

```bash
git clone https://github.com/dawnwages/lcars-online.git
cd lcars-online
scripts/setup.sh
```

`setup.sh` installs Python 3.14 and every package, creates `wagtail/LCARSAPP/.env.local` with a generated admin password and model-server key, sets up the database and admin user, fetches today's NASA data, and installs the frontend. It takes about a minute and is safe to run again.

**3. Download a model** (once; 5.7 GB):

```bash
scripts/download-models.sh qwen
```

**4. Start everything:**

```bash
scripts/start.sh
```

**5. Use it:**

1. Log in at **http://localhost:8000/admin** as `captain`. The password is in `wagtail/LCARSAPP/.env.local`.
2. Open the bridge at **http://localhost:8080**, click **Missions**, open **New mission**, choose a model, and click **Engage**.
3. Approve each gate with **Make it so** as the mission runs. A mission with a real model takes about 15–20 minutes on an M1.

Stop everything with `scripts/stop.sh`.

## The mission: seek out new worlds

The data is NASA's [Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/) (`pscomppars` table): about 6,400 confirmed planets with their orbit, size, mass, temperature, distance, and discovery method. A Prefect flow fetches it daily; the archive itself updates weekly, usually on Thursdays. A pinned snapshot from 2026-10-07 is kept in the repo, so everything also works offline.

The question the crew investigates: **is there a gap in the sizes of small planets?** This is the *radius valley* (Fulton et al. 2017), a known result: planets around 1.5–2.0 Earth radii are rare. Because the answer is known, it's a fair test of whether the crew does the analysis well.

## The crew

Each station does one narrow job with an allow-listed set of tools. Models never compute numbers.

| Station | Who | Job |
|---|---|---|
| **Ops** | Agent | Audits the data card (method counts, missing values, inferred masses, precision, what changed since the last fetch) and lists the hazards, numbered H1, H2, … |
| **Science Officer** | Agent | Writes the analysis plan **before** any results exist: the population, bandwidth, significance level, what would falsify it, and a response to every hazard. Tools: `count_population`, `column_summary`. |
| **Engineering** | Code, no model | Runs the approved plan exactly: kernel density of planet radii, Silverman's multimodality test, bootstrap interval for the valley, a specification curve across precision cuts, and a negative control. Refuses plans with invalid filters or fewer than 200 planets. |
| **Tactical** | Agent | Adversarial review: selection bias, circularity, p-hacking, power, robustness. Can accept, send back for one revision, or reject. |
| **Captain's Log** | Agent | Writes the report as a **draft** Wagtail page. |
| **Captain** | You | Approves the data card, the plan (and any revision), and publishing. |

Rules enforced in code, not prompts:

- **Every hazard gets an answer.** A plan that leaves one unanswered, or points to an invalid filter, is sent back to the model with a specific correction (and the return is logged).
- **Plans are pre-registered.** You approve the plan before Engineering computes anything.
- **Numbers come from code.** The report's numbers are checked against Engineering's results by the evals.
- **Bounded work.** Each station has a budget (requests, tool calls, 1,500-token responses, 4-minute requests), so a confused model fails fast with its output logged.
- **Everything is logged.** Every tool call, model output, decision, and approval is an append-only event in the mission log.

## Architecture

```
 LCARS bridge (Vue 3 + Vite, :8080) ──► Django / Wagtail API (:8000) ──► mission process
        ▲   launch, gates, live log          │  admin: missions, gates,        │  Prefect flow
        │                                    │  snapshots, reports            ▼
        └──── Captain's Log pages ◄──────────┘                     PydanticAI crew ──► llama.cpp (:8089)
                                                                          │            local GGUF model
 Prefect server (:4200) ── daily archive-ingest flow ──► NASA archive     ▼
                                                     snapshots ──► deterministic statistics (crew/science.py)
```

| Part | Stack | Location |
|---|---|---|
| Frontend | Vue 3.5, Vite 8, axios | `LCARS/` |
| Backend | Python 3.14, Django 6.1, Wagtail 8.0, Django REST Framework | `wagtail/LCARSAPP/` |
| Agents | [PydanticAI](https://ai.pydantic.dev/) | `wagtail/LCARSAPP/crew/agents.py` |
| Statistics | pandas, NumPy | `wagtail/LCARSAPP/crew/science.py` |
| Orchestration | [Prefect](https://www.prefect.io/): mission flows (with `PrefectDurability`) and the scheduled archive ingest | `crew/flow.py`, `crew/ingest.py` |
| Model | [llama.cpp](https://github.com/ggml-org/llama.cpp) serving a local GGUF model | `scripts/model-server.sh` |
| Evals | [DeepEval](https://deepeval.com/) metrics graded from mission logs | `wagtail/LCARSAPP/evals/` |
| Red team | [DeepTeam](https://www.trydeepteam.com/) with hard invariants | `missions/management/commands/red_team.py` |
| Mission log | Django models and admin, JSON API | `wagtail/LCARSAPP/missions/` |

## Models

Any `.gguf` file in `~/models` (or `$CREW_MODELS_DIR`) appears in the bridge's model picker; known models get a readable label and per-model settings in `wagtail/LCARSAPP/crew/models.py`. Choosing one starts its server and stops any other, so only one model is in memory.

| Model | Download | Size | Notes |
|---|---|---|---|
| Qwen3.5-9B (Q4_K_M) | `scripts/download-models.sh qwen` | 5.7 GB | Tested end to end; about 10 tokens/s on an M1 |
| Gemma 4 12B (Q4_K_M) | `scripts/download-models.sh gemma` | 7.1 GB | Loads and calls tools; about 8 tokens/s on an M1 |
| DeepSeek R1-0528 (Qwen3 8B distill, Q4_K_M) | `scripts/download-models.sh deepseek` | 5.0 GB | DeepSeek's newest model that fits a laptop (V4 Flash is 290B+ parameters). A reasoning model: about 12 tokens/s, but it thinks out loud, so it gets a 4,096-token response budget. Experimental in the crew. |
| Test model | built in | none | Random schema-valid output; for rehearsing the flow and gates, not analysis |

### llama.cpp or MLX?

The crew uses llama.cpp. Measured on an M1 (16 GB) with Qwen3.5-9B at 4-bit in each runtime, no prompt caching, 256 output tokens ([`scripts/benchmark_runtimes.py`](scripts/benchmark_runtimes.py), results in [`docs/runtime-benchmark.json`](docs/runtime-benchmark.json)):

| Workload | Runtime | First token | Generation | Total |
|---|---|---|---|---|
| Crew planning prompt (~1,000 tokens) | llama.cpp | 9.6 s | 10.2 tok/s | 34.6 s |
| Crew planning prompt (~1,000 tokens) | MLX | 10.7 s | 11.7 tok/s | 32.5 s |

MLX generates about 10–15% faster and reads prompts about 10% slower; end to end it was about 6% faster on the crew's prompt. Both return correct tool calls. On an M1 that's a modest gain; newer chips favor MLX more. Rerun it on your machine:

```bash
cd wagtail/LCARSAPP
uv run --with mlx-lm python ../../scripts/benchmark_runtimes.py --gguf ~/models/Qwen3.5-9B-Q4_K_M.gguf --mlx ~/models/mlx/Qwen3.5-9B-4bit
```

(The MLX model is a separate download, e.g. `mlx-community/Qwen3.5-9B-4bit`.)

## Services and ports

| Port | Service | Started by |
|---|---|---|
| 8080 | LCARS bridge | `scripts/start.sh` |
| 8000 | Django API, Wagtail admin (`/admin`), Django admin (`/django-admin`) | `scripts/start.sh` |
| 4200 | Prefect server and UI | `scripts/start.sh` |
| 8089 | Local model server (requires the key in `.env.local`) | the bridge, when a mission launches |

Logs and process IDs are in `wagtail/LCARSAPP/run/`. The daily data fetch runs at 06:00 America/New_York while `start.sh`'s services are up and the machine is awake.

## Commands

From `wagtail/LCARSAPP`:

```bash
uv run python manage.py run_mission                    # a mission from the terminal; gates wait for the bridge
uv run python manage.py run_mission --negative-control # the crew should find nothing
uv run python manage.py ingest_archive                 # fetch NASA data now
uv run python manage.py bakeoff --runs 1 --stations ops,science   # score the loaded model
uv run python manage.py red_team                       # DeepTeam attacks plus hard invariants
uv run python manage.py test                           # unit and integration tests (no model needed)
uv run deepeval test run evals/test_missions.py        # grade completed real-model missions
```

Real-model commands need a model server: launch from the bridge, or run `scripts/model-server.sh ~/models/<model>.gguf` and set `CREW_MODEL` to the model's name.

## Configuration

Set in the environment or in `wagtail/LCARSAPP/.env.local` (loaded automatically):

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | generated by `setup.sh` | Admin login |
| `CREW_MODEL_KEY` | generated by `setup.sh` | Key the model server requires |
| `CREW_MODELS_DIR` | `~/models` | Where `.gguf` models live |
| `CREW_MAX_TOKENS` | `1500` | Maximum tokens per model response |
| `CREW_REQUEST_TIMEOUT` | `240` | Seconds per model request |
| `CREW_TEMPERATURE` | `0.2` | Sampling temperature |
| `PREFECT_API_URL` | `http://127.0.0.1:4200/api` (set by `start.sh`) | Prefect server for schedules and run history |

## Troubleshooting

- **"Authorization required" on the bridge.** Log in at http://localhost:8000/admin first, then return to the bridge tab.
- **A port is already in use.** Run `scripts/stop.sh`, then `scripts/start.sh`. `start.sh` reports what's on a busy port rather than starting a second copy.
- **"No model loaded" or the model never comes online.** Check that a `.gguf` is in `~/models` and that `llama-server --version` works; see `wagtail/LCARSAPP/run/model-server.log`. Close memory-heavy apps: the models use 6–8 GB.
- **A mission stalls overnight.** macOS sleep pauses everything. `start.sh` keeps the Mac awake while services run; plug in power for long sessions.
- **NASA archive unreachable.** Missions use the newest snapshot on disk, or the pinned baseline. Retry with `uv run python manage.py ingest_archive`.
- **Start over with a clean database.** `scripts/stop.sh`, delete `wagtail/LCARSAPP/db.sqlite3*`, then `scripts/setup.sh`.

## Other platforms

The project is developed on macOS (Apple Silicon). On Linux, install uv, Node.js 22+, and llama.cpp (`llama-server` on your `PATH`), then follow the same steps; `caffeinate` (keeping the machine awake) is skipped automatically. Windows is untested; WSL2 is the likeliest route.

## Developer path

This project uses [uv](https://docs.astral.sh/uv/) for Python:

- Python is installed and managed by uv, pinned in `wagtail/LCARSAPP/.python-version` (3.14). Don't use the macOS system `python3` or Homebrew Python.
- One virtual environment per project, `wagtail/LCARSAPP/.venv`, created with `uv venv`.
- Top-level packages are listed in `requirements.in`; pin them for every platform with `uv pip compile requirements.in -o requirements.txt --universal --python-version 3.14`, then install with `uv pip sync requirements.txt`. uv environments have no `pip`, so "No module named pip" is expected.
- Run commands with `uv run ...`, or after `source .venv/bin/activate`.

See [AGENTS.md](AGENTS.md) for conventions when changing the code, [docs/recording.md](docs/recording.md) for recording missions, and [docs/talk-plan.md](docs/talk-plan.md) for the talk.

## Origins

LCARS Online started as a fork of [LCARS-on-Wagtail](https://github.com/dawnwages/LCARS-on-Wagtail), a headless Wagtail CMS behind an LCARS frontend.

## License

[GPL-3.0](LICENSE), the same license as the [LCARS UI](https://github.com/louh/lcars) this project builds on.

## Credits

- LCARS UI by Lou Huang ([@saikofish](https://twitter.com/saikofish), [louh/lcars](https://github.com/louh/lcars)).
- Data from the [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/), operated by the California Institute of Technology under contract with NASA.
- The radius valley: Fulton et al. 2017, *The California-Kepler Survey. III.*
- Built with Wagtail, Django, PydanticAI, Prefect, DeepEval, DeepTeam, llama.cpp, and the Qwen and Gemma open-weight models.

Star Trek and LCARS are trademarks of CBS Studios / Paramount. This is a fan project, not affiliated with or endorsed by them.

Built by Dawn Wages ([dawnwages.info](https://dawnwages.info), [Bajoran Engineer](https://dawnwages.info/bajoran-engineer/)).
