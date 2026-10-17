"""An away mission: the crew's multi-step analysis, orchestrated by Prefect.

Ops audits → [gate] → Science plans → [gate] → Engineering runs the plan →
Tactical reviews (one revision allowed) → Captain's Log drafts a report → [gate] → publish.
"""
import datetime
import json
import subprocess

import numpy as np
from django.utils import timezone
from prefect import flow, get_run_logger
from prefect.runtime import flow_run
from pydantic_ai.durable_exec.prefect import PrefectDurability
from pydantic_ai.exceptions import UnexpectedModelBehavior

from crew import science
from crew.agents import MODEL_NAME, CrewDeps, build_crew, hazard_checklist, number_hazards, run_station
from missions.models import Gate, Mission, MissionEvent, Snapshot
from missions.recorder import GateRejected, MissionRecorder

S = MissionEvent.Station
K = MissionEvent.Kind
MAX_REVISIONS = 1


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return ""


def engineering(rec, df, plan, seed, negative_control):
    """Execute the approved plan exactly. No model involved."""
    filters = [f.model_dump(exclude={"reason"}) for f in plan.population]
    with rec.tool(S.ENGINEERING, "apply_filters", filters) as box:
        subset, steps = science.apply_filters(df, filters)
        box["result"] = steps
    radii = subset["pl_rade"].dropna().to_numpy()
    if negative_control:
        with rec.tool(S.ENGINEERING, "synthetic_null", {"seed": seed}) as box:
            inside = radii[(radii >= science.WINDOW[0]) & (radii <= science.WINDOW[1])]
            radii = 10 ** science.synthetic_null(np.log10(inside), seed=seed)
            box["result"] = {"n": len(radii), "note": "radii replaced by a unimodal log-normal sample"}
    bandwidths = sorted({0.03, plan.bandwidth_dex, 0.05})
    with rec.tool(S.ENGINEERING, "analyze_radius_distribution",
                  {"bandwidths": bandwidths, "seed": seed}) as box:
        a = science.analyze_radius_distribution(radii, bandwidths=bandwidths, seed=seed)
        box["result"] = a.__dict__
    # Always run, whatever the plan says: guards against a hand-picked precision cut
    base = [f for f in filters if f["column"] != "rade_rel_err"]
    with rec.tool(S.ENGINEERING, "specification_curve", {"base_filters": base, "seed": seed}) as box:
        box["result"] = science.specification_curve(df, base, seed=seed)
    if not negative_control:
        with rec.tool(S.ENGINEERING, "negative_control", {"seed": seed}) as box:
            inside = radii[(radii >= science.WINDOW[0]) & (radii <= science.WINDOW[1])]
            null = 10 ** science.synthetic_null(np.log10(inside), seed=seed)
            c = science.analyze_radius_distribution(null, bandwidths=bandwidths, n_boot=300, seed=seed)
            box["result"] = {"silverman": c.silverman, "valley": c.valley}


def _result_json(rec):
    """Collect Engineering's tool results from the log (the source of truth)."""
    events = rec.mission.events.filter(station=S.ENGINEERING, kind=K.TOOL_RESULT)
    return {e.title: e.payload for e in events}


def _create_draft_report(rec, log):
    from home.models import HomePage
    from core.models import CorePage

    home = HomePage.objects.first()
    body = [{"type": "heading", "value": f"Captain's Log, stardate {rec.mission.stardate}"}]
    body += [{"type": "paragraph", "value": f"<p>{p}</p>"} for p in log.paragraphs]
    body += [{"type": "paragraph", "value": "<p><b>Limitations.</b> "
              + " ".join(log.limitations) + "</p>"}]
    page = CorePage(title=log.title, slug=f"mission-{rec.mission.pk}",
                    date=datetime.date.today(), intro=log.intro[:250], body=json.dumps(body),
                    live=False)
    home.add_child(instance=page)
    page.save_revision()
    rec.log(S.LOG, K.TOOL_RESULT, "Created draft report page", payload={"page_id": page.pk})
    return page


@flow(name="away-mission", log_prints=True)
def away_mission(mission_id: int, gate_policies: dict | None = None):
    """gate_policies maps a gate name to {"decision", "via"}; missing gates wait for a person."""
    gate_policies = gate_policies or {}
    logger = get_run_logger()
    mission = Mission.objects.get(pk=mission_id)
    rec = MissionRecorder(mission)
    negative_control = mission.kind == Mission.Kind.NEGATIVE_CONTROL
    rec.set_status(Mission.Status.RUNNING, started_at=timezone.now(), model_name=MODEL_NAME,
                   prefect_flow_run_id=str(flow_run.id or ""), code_version=_git_commit())
    crew = build_crew(capabilities=[PrefectDurability()])

    try:
        # Ops: audit the newest recorded snapshot (fetched on schedule by crew/ingest.py)
        from crew.ingest import ensure_baseline
        snapshot = Snapshot.latest_usable() or ensure_baseline()
        with rec.tool(S.OPS, "load_snapshot", {"path": snapshot.path,
                                               "fetched_at": snapshot.fetched_at.isoformat()}) as box:
            df, sha = science.load_snapshot(snapshot.path, snapshot.sha256)
            box["result"] = {"rows": len(df), "sha256": sha,
                             "fetched_at": snapshot.fetched_at.isoformat()}
        rec.set_status(Mission.Status.RUNNING, snapshot_sha256=sha, snapshot=snapshot)
        with rec.tool(S.OPS, "data_card", {}) as box:
            card = science.data_card(df)
            source = snapshot.content_source()
            card["snapshot_fetched_at"] = source.fetched_at.isoformat()
            card["archive_last_checked_at"] = snapshot.fetched_at.isoformat()
            changes = source.changes or {}
            if changes.get("baseline"):
                card["changes_since_previous_snapshot"] = "baseline snapshot; nothing to compare"
            else:
                card["changes_since_previous_snapshot"] = {
                    k: changes.get(k) for k in ("added", "removed", "revised", "added_by_method")}
            box["result"] = card
        deps = CrewDeps(recorder=rec, df=df)
        brief = run_station(crew["ops"], S.OPS,
                            f"Data card:\n{json.dumps(card, default=str)}", deps)
        deps.hazards = number_hazards(brief)
        for h in deps.hazards:
            rec.log(S.OPS, K.DECISION, f"Hazard {h['id']}: {h['name']}", rationale=h["implication"],
                    payload={"evidence": h["evidence"]})
        rec.request_gate(Gate.Name.DATA_CARD, {"brief": brief.model_dump(), "data_card": card},
                         policy=gate_policies.get(Gate.Name.DATA_CARD))

        feedback = ""
        for attempt in range(MAX_REVISIONS + 1):
            # Science Officer: pre-register the plan
            plan = run_station(crew["science"], S.SCIENCE, (
                f"Question: {mission.question}\n\nOps brief:\n{brief.summary}\n\n"
                f"{hazard_checklist(deps.hazards)}\n\nColumns: {card['columns']}\n{feedback}"), deps)
            rec.log(S.SCIENCE, K.DECISION, f"Analysis plan (attempt {attempt + 1})",
                    rationale=plan.hypothesis,
                    alternatives=[a.model_dump() for a in plan.alternatives_considered],
                    payload=plan.model_dump())
            rec.set_status(Mission.Status.RUNNING, plan=plan.model_dump())
            # Every plan, including a revision, is approved before it runs
            gate = Gate.Name.PLAN if attempt == 0 else Gate.Name.PLAN_REVISION
            rec.request_gate(gate, {**plan.model_dump(), "hazards": deps.hazards},
                             policy=gate_policies.get(gate))

            # Engineering: run it exactly, or refuse if the sample can't support the test
            try:
                engineering(rec, df, plan, mission.seed, negative_control)
            except science.InsufficientSample as exc:
                rec.log(S.ENGINEERING, K.DECISION, "Plan refused: sample too small",
                        rationale=str(exc))
                if attempt == MAX_REVISIONS:
                    raise
                feedback = (f"Engineering refused the previous plan: {exc}. "
                            "Use count_population to check the sample before committing.")
                continue
            results = _result_json(rec)
            rec.set_status(Mission.Status.RUNNING, result=results)

            # Tactical: try to break it
            review = run_station(crew["tactical"], S.TACTICAL, (
                f"Question: {mission.question}\nPlan:\n{plan.model_dump_json()}\n"
                f"Results:\n{json.dumps(results, default=str)}"), deps)
            for issue in review.issues:
                rec.log(S.TACTICAL, K.DECISION, f"{issue.severity} {issue.category}",
                        rationale=issue.detail)
            rec.log(S.TACTICAL, K.DECISION, f"Verdict: {review.verdict}",
                    rationale=review.summary, payload=review.model_dump())
            rec.set_status(Mission.Status.RUNNING, review=review.model_dump())
            if review.verdict != "revise":
                break
            feedback = ("Tactical asked for a revision of the previous plan:\n"
                        + review.model_dump_json())

        # Captain's Log: draft, then a person publishes
        log = run_station(crew["log"], S.LOG, (
            f"Question: {mission.question}\nPlan:\n{plan.model_dump_json()}\n"
            f"Results:\n{json.dumps(results, default=str)}\nReview:\n{review.model_dump_json()}"),
            deps)
        page = _create_draft_report(rec, log)
        rec.set_status(Mission.Status.RUNNING, report_page=page, verdict=log.intro[:200])
        rec.request_gate(Gate.Name.PUBLISH, {"page_id": page.pk, "title": log.title},
                         policy=gate_policies.get(Gate.Name.PUBLISH))
        page.get_latest_revision().publish()
        rec.log(S.CAPTAIN, K.NOTE, "Captain's Log published", payload={"page_id": page.pk})
        rec.set_status(Mission.Status.COMPLETE, finished_at=timezone.now())
    except science.InsufficientSample as exc:
        rec.set_status(Mission.Status.FAILED, finished_at=timezone.now(),
                       verdict=f"No valid plan: {exc}")
    except UnexpectedModelBehavior as exc:
        rec.log(S.SYSTEM, K.ERROR, f"Model could not produce valid output: {exc}")
        rec.set_status(Mission.Status.FAILED, finished_at=timezone.now(),
                       verdict=("No valid plan: the crew could not produce output that passes "
                                "its checks (for example, answering every hazard) within its retries"))
    except GateRejected as exc:
        logger.info("Mission stopped at a gate: %s", exc)
    except Exception as exc:
        rec.log(S.SYSTEM, K.ERROR, f"Mission failed: {exc}")
        rec.set_status(Mission.Status.FAILED, finished_at=timezone.now())
        raise
    return mission.pk
