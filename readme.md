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

## The analysis: is there a gap in the sizes of small planets?

### The science

Planets between Earth's size and about four times Earth's size fall into two groups: **super-Earths** near 1.3 Earth radii (rocky, with little atmosphere) and **sub-Neptunes** near 2.4 Earth radii (rocky cores inside thick gas envelopes). Planets in between, about 1.5–2.0 Earth radii, are rare. This **radius valley** was first measured clearly by Fulton et al. (2017), *The California-Kepler Survey. III*. The leading explanation is that starlight, or heat from the planet's own core, strips the atmosphere from smaller planets close to their stars.

Because the answer is known, the question is a fair test of whether the crew does the analysis well. The project tests a process; it doesn't make a discovery.

### The data

NASA's [Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/), table `pscomppars`: one row per confirmed planet, with the best available value for each of 20 columns, including radius and its error, mass and how it was obtained, orbital period, discovery method, and host-star properties. There were 6,375 planets on 2026-10-07 and 6,451 on 2026-10-17.

- **Freshness.** A Prefect flow fetches the archive daily, validates it, and saves a snapshot with its SHA-256 hash and a record of which planets were added, removed, or revised. The archive itself updates weekly, usually on Thursdays.
- **Reproducibility.** Each mission records the snapshot it analyzed. The 2026-10-07 snapshot is pinned in the repo (`crew/data/`) and is the ground truth for the tests.
- **Facts any analysis must handle** (the data card Ops reviews):
  - **Discovery method shapes the catalog.** About 74% of planets were found by transit, which favors short orbits (median 8 days); radial-velocity planets have a median orbit of 305 days.
  - **About 47% of masses are inferred** from a mass–radius relation, not measured. This method uses radius only.
  - **Radius precision varies widely.** The median relative error is about 8%.

### The method

Every number below is computed by deterministic code in [`crew/science.py`](wagtail/LCARSAPP/crew/science.py). The Science Officer chooses the population, bandwidth, and significance level, and you approve that plan before anything runs.

1. **Population.** Apply the approved filters in order (for example, transit-discovered planets with radius error under 15%), then keep planets between 1 and 4 Earth radii. Plans that leave fewer than 200 planets are refused.
2. **Size distribution.** A Gaussian kernel density estimate of log₁₀(radius) on 400 points across the window, at the plan's bandwidth (0.02–0.08 dex), and also at 0.03 and 0.05 dex for comparison.
3. **Silverman's test for multimodality** (Silverman 1981).
   - **Null hypothesis:** the distribution has at most one mode.
   - **Critical bandwidth:** find h_crit, the smallest bandwidth at which the estimate has one mode, by bisection.
   - **p-value:** draw 500 smoothed bootstrap samples at h_crit with Silverman's variance correction; p is the share of them that still have more than one mode.
   - **Reading it:** a small p is evidence of a valley. The test is conservative.
4. **Valley location.** The lowest point between the two highest peaks, its depth relative to those peaks, and a 95% percentile interval for its location from 500 bootstrap resamples. The run also reports how often a valley appears at all.
5. **Specification curve.** This always runs, whatever the plan says. The analysis is repeated with no precision cut and with radius error under 20%, 15%, 10%, 8%, and 5%. A conclusion has to hold across the sweep, not just at one cut chosen after seeing the results.
6. **Negative control.** The radii are replaced with a log-normal sample of the same size, mean, and spread, which has one peak by construction, and the test is rerun. It should find nothing. In a *negative-control mission*, this synthetic sample is the whole analysis.
7. **Interpretation, in code.** Engineering states whether the main test is significant at the plan's alpha, whether the negative control **PASSED** or **FAILED**, and how many precision cuts agree. Agents critique these statements; they don't recompute them.

### Reading the results

| You see | It means |
|---|---|
| p below alpha, valley at 1.5–2.1 Earth radii, tight interval, holds across the sweep, negative control passes | Evidence for two groups of planet sizes, consistent with the published valley |
| A valley is visible, but p is at or above alpha | **Not** evidence of no valley. Usually there are too few planets for the test: report "not significant at this sample size" |
| Significant at one precision cut but not at its neighbors | Fragile. Picking that cut after seeing the results would be p-hacking |
| Significant only when all discovery methods are mixed | Suspect. Mixed selection effects can create or hide structure |
| The negative control finds a valley | The method is broken; trust nothing from that mission |
| Plan refused | An invalid filter or too few planets; Engineering won't run a test that can't mean anything |

### What the data shows

These figures come from this code, run on the pinned 2026-10-07 snapshot, transit-discovered planets only:

| Radius error cut | Planets in window | Silverman p | Valley (Earth radii) | 95% interval |
|---|---|---|---|---|
| none | 3,291 | 0.017 | 1.73 | 1.66–1.83 |
| < 15% | 1,858 | 0.010 | 1.74 | 1.61–1.81 |
| < 10% | 1,421 | < 0.003 | 1.75 | 1.66–1.82 |
| < 5% | 575 | 0.18 | 1.74 | 1.35–1.83 |

- **Location:** the valley sits at 1.72–1.76 Earth radii at every cut.
- **Significance:** it's significant wherever enough planets remain, and not at the strictest cut, which shows the trade-off between precision and statistical power.
- **Negative control:** it finds nothing (p ≈ 0.5).
- **On current data:** missions on the 2026-10-17 data with a 15% cut found the same picture: 1,938 planets, p = 0.004, valley at 1.75 Earth radii (95% interval 1.66–1.82), negative control passed.

### Limits an expert would raise

- **No completeness correction.** The crew counts planets in the catalog, not the true population. Fulton et al. corrected for which planets a survey could detect; this analysis does not.
- **Selection effects.** Transit dominates the sample, so a valley can partly reflect what surveys are able to detect.
- **A composite catalog.** Values come from many studies and pipelines.
- **A conservative test.** Silverman's test can miss shallow valleys, and the result depends on sample size and precision.
- **A known answer.** Rediscovering a published result tests the process; it is not a discovery.
- **A small local model.** The numbers are computed and checked by code, but a 9-billion-parameter model can still misread or misattribute results in its prose. Read the mission's event log, not just its report.

The bridge's **Briefing** screen and the **disclaimer** bar on the Missions screen present the same material.

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

The crew uses llama.cpp. Measured on an M1 (16 GB) with Qwen3.5-9B at 4-bit in each runtime, no prompt caching, 256 output tokens ([`scripts/benchmark_runtimes.py`](scripts/benchmark_runtimes.py), results in [`docs/runtime-benchmark-apple-m1-16gb.json`](docs/runtime-benchmark-apple-m1-16gb.json)):

| Workload | Runtime | First token | Generation | Total |
|---|---|---|---|---|
| Crew planning prompt (~1,000 tokens) | llama.cpp | 9.6 s | 10.2 tok/s | 34.6 s |
| Crew planning prompt (~1,000 tokens) | MLX | 10.7 s | 11.7 tok/s | 32.5 s |

MLX generates about 9–15% faster and reads prompts about 10% slower; end to end it was about 6% faster on the crew's prompt. Both return correct tool calls. On an M1 that's a modest gain; newer chips favor MLX more. Rerun it on your machine:

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

## When missions fail

A **failed** mission is one that didn't reach a Captain's Log you could publish. It doesn't mean the analysis found no valley: often Engineering has already computed correct statistics, and they remain in the mission log. The crew is built to **fail closed**: when something can't be done within the rules, it stops rather than letting unchecked output through.

| Kind | What happened | Verdict shown |
|---|---|---|
| **Invalid output within limits** | An agent kept being sent back by a check (unanswered hazard, invalid filter, invented number, missing statistics) or used up its budget of requests, tool calls, response length, or time | "The crew could not produce valid output within its limits…" |
| **No valid plan** | Engineering refused the plan (an invalid filter or fewer than 200 planets) and no valid revision followed | "No valid plan: …" |
| **Infrastructure** | The model server didn't load, the machine slept, or the mission process stopped | "Model … did not come online" or "Interrupted: …" |
| **Rejected** (separate status) | A person said no at a gate: a decision, not a failure | Status **Rejected** |

Some problems don't fail the mission; the report says so instead:

- **The reviewer can't produce a valid review.** The report uses the result and states it was not independently challenged.
- **A requested revision can't be produced, or Engineering refuses it.** The report uses the approved plan's result and lists the reviewer's issues as unresolved.

**Reading a failure.** The mission's verdict says which kind it was. In its event log, red **Error** entries show where it stopped, and **Plan returned**, **Review returned**, and **Report returned** notes show what each check objected to, with the model's last output attached.

**Failures that shaped the guardrails.** Each of these happened in a real mission and led to a fix:

| What failed | Fix |
|---|---|
| A tool returned 0 planets for a filter with no value, and the planner spent 34 minutes debugging it | Tools refuse malformed filters with the reason and the valid values |
| The planner ignored the hazards Ops raised, every time | Every hazard must be answered, checked in code |
| The planner filtered on mass to answer a hazard about masses, though the method uses radius only; n fell from 3,352 to 621 and the report said "No Evidence for a Gap" | A `not_applicable` response, and a rule against filtering on columns the method never uses |
| The reviewer cited p-values and percentages nothing had computed | Reviews and reports may cite only numbers from results, the data card, or counts they ran |
| The reviewer read a passing negative control as a failure | Engineering states each result's meaning in code |
| Constrained tool calls left out an optional filter value even when the model's text named it | The value is a required field |
| Text filters like `transit` (the code is `tran`) matched nothing | Values that never occur are refused, listing the real ones |

Known limit: the number check catches invented numbers, not a real number attributed to the wrong analysis. Read the event log, not just the report.

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
