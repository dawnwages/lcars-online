"""Compare local models on the crew's real tasks, with deterministic scoring.

Start a model with scripts/model-server.sh, then:
    uv run python manage.py bakeoff --runs 3
Results are logged as an Eval mission in the admin and printed as a table.
"""
import json
import statistics
import time

from django.core.management.base import BaseCommand
from django.utils import timezone
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import RetryPromptPart, ToolCallPart

from crew import agents, science
from missions.models import Mission, MissionEvent
from missions.recorder import MissionRecorder

QUESTION = "Is there a gap in the sizes of small planets?"


def flawed_results():
    """Results Tactical must not accept: the negative control found a valley."""
    return {
        "analyze_radius_distribution": {"n": 1374, "silverman": {"p_value": 0.003},
                                        "valley": {"radius_earth": 1.756}},
        "specification_curve": [
            {"radius_rel_err_lt": 0.08, "n": 1110, "p_value": 0.14},
            {"radius_rel_err_lt": 0.10, "n": 1374, "p_value": 0.003},
            {"radius_rel_err_lt": 0.15, "n": 1793, "p_value": 0.013}],
        "negative_control": {"silverman": {"p_value": 0.004},
                             "valley": {"radius_earth": 2.1, "depth_ratio": 0.7}},
    }


class Command(BaseCommand):
    help = "Score the currently served local model on each crew station."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=3)
        parser.add_argument("--stations", default="ops,science,tactical,log",
                            help="Comma-separated stations to score (Science needs Ops first)")

    def handle(self, runs, stations, **options):
        stations = set(stations.split(","))
        df, sha = science.load_snapshot()
        card = science.data_card(df)
        mission = Mission.objects.create(question=f"Model bake-off: {agents.MODEL_NAME}",
                                         kind=Mission.Kind.EVAL, model_name=agents.MODEL_NAME,
                                         snapshot_sha256=sha, status=Mission.Status.RUNNING,
                                         started_at=timezone.now())
        rec = MissionRecorder(mission)
        deps = agents.CrewDeps(recorder=rec, df=df)
        crew = agents.build_crew()
        scores = {k: [] for k in ("ops", "science", "tactical", "log")}

        def timed(agent, station, prompt):
            rec.current_station = station
            start = time.monotonic()
            with capture_run_messages() as messages:
                try:
                    result = agent.run_sync(prompt, deps=deps,
                                            usage_limits=agents.STATION_LIMITS.get(station))
                except Exception as exc:
                    failure = agents.describe_failure(messages)
                    rec.log(station, MissionEvent.Kind.ERROR, f"{agent.name} failed: {exc}"[:300],
                            payload=failure, duration_ms=int((time.monotonic() - start) * 1000))
                    return None, time.monotonic() - start, {"failure": failure}
            msgs = result.all_messages()
            meta = {
                "retries": sum(isinstance(p, RetryPromptPart) for m in msgs for p in m.parts),
                "tools": [p.tool_name for m in msgs for p in m.parts if isinstance(p, ToolCallPart)],
                "output_tokens": result.usage.output_tokens,
            }
            elapsed = time.monotonic() - start
            rec.log(station, MissionEvent.Kind.MODEL_OUTPUT, f"{agent.name} output",
                    payload={"output": result.output.model_dump(), **meta},
                    model_name=agents.MODEL_NAME, output_tokens=meta["output_tokens"],
                    duration_ms=int(elapsed * 1000))
            return result.output, elapsed, meta

        for i in range(runs):
            self.stdout.write(f"Run {i + 1}/{runs}")
            brief, t, meta = timed(crew["ops"], "ops", f"Data card:\n{json.dumps(card, default=str)}")
            text = brief.model_dump_json().lower() if brief else ""
            scores["ops"].append({"valid": brief is not None, "seconds": t, **meta, "checks": {
                "flags_inferred_masses": "m-r" in text or "mass-radius" in text or "inferred" in text,
                "flags_method_selection": "selection" in text or "discovery method" in text,
            }})

            if "science" not in stations:
                plan = None
            else:
                deps.hazards = agents.number_hazards(brief) if brief else []
                returns_before = mission.events.filter(title="Plan returned: hazards not answered or filters invalid").count()
                plan, t, meta = timed(crew["science"], "science", (
                    f"Question: {QUESTION}\nOps brief:\n{brief.summary if brief else ''}\n\n"
                    f"{agents.planning_facts(card)}\n\n{agents.hazard_checklist(deps.hazards)}\n\n"
                    f"Columns: {card['columns']}"))
                meta["hazard_returns"] = mission.events.filter(
                    title="Plan returned: hazards not answered or filters invalid").count() - returns_before
            checks = {}
            if plan:
                filters = [f.model_dump(exclude={"reason"}) for f in plan.population]
                cols = {(f["column"], f["op"], str(f["value"])) for f in filters}
                try:
                    subset, _ = science.apply_filters(df, filters)
                    r = subset["pl_rade"].dropna()
                    n = int(((r >= 1) & (r <= 4)).sum())
                except Exception:
                    n = 0
                checks = {
                    "answers_every_hazard": not agents.hazard_problems(plan, deps.hazards),
                    "restricts_to_transit": ("disc_method", "eq", "tran") in cols,
                    "cuts_radius_precision": any(c[0] == "rade_rel_err" for c in cols),
                    "checked_sample_size": "count_population" in meta.get("tools", []),
                    "enough_planets": n >= science.MIN_SAMPLE,
                    "states_falsification": len(plan.falsification) > 20,
                }
            if "science" in stations:
                scores["science"].append({"valid": plan is not None, "seconds": t, **meta,
                                          "checks": checks})
            if not stations & {"tactical", "log"}:
                continue

            review, t, meta = timed(crew["tactical"], "tactical", (
                f"Question: {QUESTION}\nResults:\n{json.dumps(flawed_results())}"))
            scores["tactical"].append({"valid": review is not None, "seconds": t, **meta, "checks": {
                "rejects_broken_negative_control": bool(review) and review.verdict != "accept",
            }})

            log, t, meta = timed(crew["log"], "log", (
                f"Question: {QUESTION}\nResults: valley at 1.756 Earth radii, 95% interval "
                "1.668-1.824, Silverman p=0.003 with n=1374 transiting planets with radius error "
                "under 10%. The valley appears at 1.72-1.76 across all precision cuts; p ranges "
                "0.000-0.203 and is not significant at the strictest cuts. Negative control: p=0.53."))
            text = log.model_dump_json() if log else ""
            scores["log"].append({"valid": log is not None, "seconds": t, **meta, "checks": {
                "reports_location": "1.7" in text,
                "reports_uncertainty": "1.668" in text or "1.67" in text or "interval" in text.lower(),
                "mentions_robustness_limits": "0.203" in text or "strict" in text.lower(),
            }})

        summary = {}
        for station, rows in scores.items():
            if not rows:
                continue
            checks = [v for r in rows for v in r["checks"].values()]
            summary[station] = {
                "valid_pct": round(100 * sum(r["valid"] for r in rows) / len(rows)),
                "checks_pct": round(100 * sum(checks) / len(checks)) if checks else 0,
                "median_seconds": round(statistics.median(r["seconds"] for r in rows), 1),
                "retries": sum(r.get("retries", 0) for r in rows),
                "hazard_returns": sum(r.get("hazard_returns", 0) for r in rows),
            }
        rec.set_status(Mission.Status.COMPLETE, finished_at=timezone.now(),
                       result={"summary": summary, "runs": scores},
                       verdict=json.dumps({k: v["checks_pct"] for k, v in summary.items()}))
        self.stdout.write(f"\n{agents.MODEL_NAME} ({agents.OUTPUT_MODE} output), {runs} runs")
        self.stdout.write(f"{'station':10} {'valid%':>7} {'checks%':>8} {'med s':>7} {'retries':>8} {'hazard returns':>15}")
        for station, s in summary.items():
            self.stdout.write(f"{station:10} {s['valid_pct']:7} {s['checks_pct']:8} "
                              f"{s['median_seconds']:7} {s['retries']:8} {s['hazard_returns']:15}")
        if "science" in scores:
            for i, r in enumerate(scores["science"], 1):
                self.stdout.write(f"  science run {i}: {r['checks']}")
        self.stdout.write(f"Logged as mission {mission.pk}")
