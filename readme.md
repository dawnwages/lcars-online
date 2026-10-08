# LCARS Online

<img src="UnitedFederationofPlanets.png" alt="United Federation of Planets Logo" height="100" max-width="200"/><img src="Vue.js_Logo.png" alt="Vue JS Logo" height="100" max-width="200"/><img src="wagtail-logo.png" alt="Wagtail Logo" height="100" maxwidth="200"/>

**What if your data science dashboard looked like the bridge of the Enterprise, and actually worked like it too?**

LCARS Online is a Star Trek LCARS interface on top of a crew of AI agents. The agents explore real data: every confirmed exoplanet in NASA's Exoplanet Archive. Each agent has one job and a short list of tools: bringing in the data, finding anomalies, answering questions in plain English, and writing reports.

This is the companion repo for **[To Boldly Go: Data Science Exploration with AI Agents (ft Star Trek's LCARS theme)](https://2026.allthingsopen.org/sessions/to-boldly-go-data-science-exploration-with-ai-agents-ft-star-treks-lcars-theme)** at All Things Open 2026, Tuesday, October 20, 10:30 to 11:00 a.m. ET, Raleigh, NC.

> **Status:** in development for the talk. The LCARS frontend and the Wagtail backend run today. The agent crew below is the plan and is being built. See [docs/talk-plan.md](docs/talk-plan.md).

## The mission: seek out new worlds

The data is NASA's [Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/): 6,375 confirmed planets (as of October 2026), discovered from 1992 to today. Each planet has its orbit, size, mass, temperature, distance, and discovery method. The archive has a free public API with no key required, and the demo also ships with a saved snapshot so it runs without conference Wi-Fi.

## The crew

Agentic AI in data science means a coordinated team of specialized agents, not one chatbot. Each crew member does one narrow job, can use only the tools on its own list, and logs everything it does.

| Station | Agent | Job | Tools it may use |
|---|---|---|---|
| Operations | **Ops** | Data ingestion: fetch the archive, validate the schema, store a snapshot | Archive API (read), snapshot writer |
| Science | **Science Officer** | Anomaly detection: find planets that don't fit the pattern, and explain why | Outlier scan over planet properties |
| Computer | **Computer** | Natural-language questions: "Computer, how many planets were found by transit since 2020?" | Read-only SQL with a row limit |
| Captain's Log | **Log** | Report generation: summarize a mission as a Captain's Log entry | Create a **draft** Wagtail page |
| Bridge | **Bridge** | Routes each request to the right crew member | Hand-offs to the crew |

Rules this crew follows, all enforced in code, not just in prompts:

- **Read-only data access.** The Computer can't modify the database. Queries are checked as `SELECT`-only and capped in size.
- **A human publishes.** The Log agent can only create drafts. A person reviews and publishes each report in the Wagtail admin.
- **Every run is recorded.** Every agent run, tool call, and approval is logged.
- **Memory is the Captain's Log.** Published reports become context for later missions.

## Architecture

```
LCARS (Vue 3 + Vite)  ──►  Wagtail / Django API  ──►  Agent crew (PydanticAI)
        ▲                        │                          │
        │                        ▼                          ▼
   Captain's Log pages  ◄──  Wagtail admin (human     Exoplanet snapshot
   (published reports)       review + publish)        (read-only)
                                                            ▲
                                Prefect: scheduled "away missions"
                                (ingest → scan → log), retries, run history
```

| Part | Stack | Location |
|---|---|---|
| Frontend | Vue 3.5, Vite 8, axios | `LCARS/` |
| Backend | Python 3.14, Django 6.1, Wagtail 8.0, Django REST Framework | `wagtail/LCARSAPP/` |
| Agents | [PydanticAI](https://ai.pydantic.dev/) | planned |
| Orchestration | [Prefect](https://www.prefect.io/), made durable with PydanticAI's `PrefectDurability` capability | planned |
| Evals | [DeepEval](https://deepeval.com/): graded against known answers and tool calls, not just prose | planned |

Still undecided: which model provider to use, and which data store to use for the planet snapshot.

## Installation

You need [uv](https://docs.astral.sh/uv/) for the backend and Node.js for the frontend. Run them in separate terminals.

### Backend: Wagtail CMS

```bash
cd wagtail/LCARSAPP
uv venv
uv pip sync requirements.txt
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

The API runs at http://localhost:8000/api/v2/ and the Wagtail admin at http://localhost:8000/admin/.

### Frontend: LCARS (Vue + Vite)

```bash
cd LCARS
npm install
npm start
```

The app runs at http://localhost:8080, the origin the backend's CORS settings allow.

## Testing

```bash
cd wagtail/LCARSAPP
uv run python manage.py test
```

The agent evals will live alongside the tests. Each graded question has a known answer, so "the Computer said something plausible" doesn't count as passing.

## Developer path

This project uses [uv](https://docs.astral.sh/uv/) for Python:

- Python is installed and managed by uv, pinned in `wagtail/LCARSAPP/.python-version` (3.14). Don't use the macOS system `python3` or Homebrew Python.
- One virtual environment per project, `wagtail/LCARSAPP/.venv`, created with `uv venv`.
- Top-level packages are listed in `requirements.in` and pinned in `requirements.txt` with `uv pip compile requirements.in -o requirements.txt`. uv environments have no `pip`, so "No module named pip" is expected.
- Run commands with `uv run ...`, or after `source .venv/bin/activate`.

## Origins

LCARS Online started as a fork of [LCARS-on-Wagtail](https://github.com/dawnwages/LCARS-on-Wagtail), a headless Wagtail CMS behind an LCARS frontend.

## License

[GPL-3.0](LICENSE), the same license as the [LCARS UI](https://github.com/louh/lcars) this project builds on.

## Credits

Shout out to Lou Huang ([@saikofish](https://twitter.com/saikofish), [louh/lcars](https://github.com/louh/lcars)) for the LCARS UI. Exoplanet data comes from the NASA Exoplanet Archive, operated by Caltech under contract with NASA.

Built by Dawn Wages:

- Website: [dawnwages.info](https://dawnwages.info)
- Blog: [Bajoran Engineer](https://dawnwages.info/bajoran-engineer/)
