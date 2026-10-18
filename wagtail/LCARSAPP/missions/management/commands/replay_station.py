"""Replay one crew station on a past mission's real inputs, several times.

    uv run python manage.py replay_station --mission 14 --station log --runs 3
    uv run python manage.py replay_station --mission 14 --station tactical --runs 3

Finds a station's failure modes in minutes instead of one per 30-minute mission.
Each replay is logged as an Eval mission (visible in the admin), with every
returned output and error, and a summary table is printed. Needs the model server
(CREW_MODEL set to the loaded model).
"""
import json
import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from pydantic_ai import capture_run_messages

from crew import agents, science
from crew.schemas import AnalysisPlan, Review
from missions.models import Mission, MissionEvent
from missions.recorder import MissionRecorder


def _inputs(source):
    """Rebuild what a station saw, from the source mission's log."""
    events = source.events
    card_event = events.filter(title="data_card", kind=MissionEvent.Kind.TOOL_RESULT).first()
    if not (source.plan and source.result and card_event):
        raise CommandError(f"Mission {source.pk} has no plan, results, or data card to replay")
    hazards = [{"id": e.title.split(":")[0].replace("Hazard ", ""), "name": e.title.split(": ", 1)[1],
                "evidence": (e.payload or {}).get("evidence", ""), "implication": e.rationale}
               for e in events.filter(station="ops", kind="decision", title__startswith="Hazard ")]
    return {"card": card_event.payload, "plan": AnalysisPlan(**source.plan),
            "results": source.result, "review": Review(**source.review) if source.review else None,
            "hazards": hazards}


class Command(BaseCommand):
    help = "Replay one station (tactical or log) on a past mission's inputs."

    def add_arguments(self, parser):
        parser.add_argument("--mission", type=int, required=True)
        parser.add_argument("--station", choices=["tactical", "log"], required=True)
        parser.add_argument("--runs", type=int, default=3)

    def handle(self, mission, station, runs, **options):
        source = Mission.objects.get(pk=mission)
        x = _inputs(source)
        replay = Mission.objects.create(
            question=f"Replay {station} on mission {mission} ({runs} runs)", kind=Mission.Kind.EVAL,
            model_name=agents.MODEL_NAME, snapshot_sha256=source.snapshot_sha256,
            status=Mission.Status.RUNNING, started_at=timezone.now())
        rec = MissionRecorder(replay)
        df, _ = science.load_snapshot(source.snapshot.path, source.snapshot_sha256) \
            if source.snapshot else science.load_snapshot()
        crew = agents.build_crew()
        evidence = [json.dumps(x["results"], default=str), x["plan"].model_dump_json()]
        if station == "log" and x["review"]:
            evidence.append(x["review"].model_dump_json())
        if station == "tactical":
            evidence.append(json.dumps(x["card"], default=str))
            prompt = (f"Question: {source.question}\n{agents.planning_facts(x['card'])}\n"
                      f"Plan:\n{x['plan'].model_dump_json()}\n"
                      f"Results:\n{json.dumps(x['results'], default=str)}")
        else:
            prompt = (f"Question: {source.question}\nPlan:\n{x['plan'].model_dump_json()}\n"
                      f"Results:\n{json.dumps(x['results'], default=str)}\n"
                      f"Review:\n{x['review'].model_dump_json() if x['review'] else 'none'}")

        outcomes = []
        for i in range(runs):
            deps = agents.CrewDeps(recorder=rec, df=df, hazards=x["hazards"], evidence=list(evidence))
            before = replay.events.filter(kind=MissionEvent.Kind.NOTE).count()
            start = time.monotonic()
            with capture_run_messages():
                try:
                    agents.run_station(crew[station], station, prompt, deps)
                    ok, why = True, "valid"
                except Exception as exc:
                    ok, why = False, type(exc).__name__ + ": " + str(exc)[:120]
            returns = replay.events.filter(kind=MissionEvent.Kind.NOTE).count() - before
            outcomes.append({"run": i + 1, "ok": ok, "returns": returns, "why": why,
                             "seconds": round(time.monotonic() - start)})
            self.stdout.write(f"  run {i + 1}: {'valid' if ok else 'FAILED'} after {returns} returns "
                              f"in {outcomes[-1]['seconds']}s  {'' if ok else why}")

        reasons = Counter(e.rationale[:80] for e in replay.events.filter(kind=MissionEvent.Kind.NOTE))
        passed = sum(o["ok"] for o in outcomes)
        rec.set_status(Mission.Status.COMPLETE, finished_at=timezone.now(),
                       verdict=f"{station}: {passed}/{runs} valid",
                       result={"outcomes": outcomes, "return_reasons": dict(reasons)})
        self.stdout.write(f"\n{station} on mission {mission}: {passed}/{runs} valid "
                          f"(logged as mission {replay.pk})")
        for reason, n in reasons.most_common(5):
            self.stdout.write(f"  returned {n}x: {reason}")
