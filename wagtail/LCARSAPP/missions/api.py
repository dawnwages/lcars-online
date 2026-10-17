"""JSON API for the LCARS bridge: mission log (read-only) and gate decisions.

Reads are open, like the Wagtail page API. Deciding a gate requires a logged-in
user with permission to change gates, and is recorded the same way as in the admin.
"""
import json

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Gate, Mission, MissionEvent, Snapshot
from .recorder import MissionRecorder

LIVE = (Mission.Status.PLANNED, Mission.Status.RUNNING, Mission.Status.AWAITING_APPROVAL)

BRIDGE = "LCARS bridge"


def _mission_summary(m):
    return {
        "id": m.pk, "stardate": m.stardate, "question": m.question, "kind": m.kind,
        "status": m.status, "status_display": m.get_status_display(), "verdict": m.verdict,
        "model_name": m.model_name, "created_at": m.created_at.isoformat(),
        "duration_s": int(m.duration.total_seconds()) if m.duration else None,
        "pending_gates": sum(g.status == Gate.Status.PENDING for g in m.gates.all()),
        "event_count": m.events.count(),
    }


def _snapshot(s):
    if not s:
        return None
    src = s.content_source()
    changes = src.changes or {}
    return {"id": s.pk, "data_fetched_at": src.fetched_at.isoformat(),
            "last_checked_at": s.fetched_at.isoformat(), "rows": src.rows,
            "sha256": src.sha256, "baseline": bool(changes.get("baseline")),
            "added": changes.get("added"), "removed": changes.get("removed"),
            "revised": changes.get("revised")}


def _gate(g):
    return {
        "id": g.pk, "name": g.name, "label": g.get_name_display(), "status": g.status,
        "requested_at": g.requested_at.isoformat(),
        "decided_at": g.decided_at.isoformat() if g.decided_at else None,
        "decided_by": str(g.decided_by or ""), "decided_via": g.decided_via, "note": g.note,
        # What the person is being asked to approve: the payload of the request event
        "summary": (g.mission.events.filter(kind="gate", title__endswith=g.get_name_display())
                    .order_by("seq").values_list("payload", flat=True).first()),
    }


@require_GET
def session(request):
    """Who is on the bridge, and a CSRF token for decisions."""
    user = request.user
    return JsonResponse({
        "authenticated": user.is_authenticated,
        "username": user.get_username() if user.is_authenticated else "",
        "can_decide": user.is_authenticated and user.has_perm("missions.change_gate"),
        "can_launch": user.is_authenticated and user.has_perm("missions.add_mission"),
        "csrf_token": get_token(request),
    })


@require_GET
def mission_list(request):
    missions = Mission.objects.prefetch_related("gates")[:50]
    return JsonResponse({"missions": [_mission_summary(m) for m in missions]})


@require_GET
def mission_detail(request, pk):
    """Mission with gates and events. `?since=<seq>` returns only newer events."""
    m = get_object_or_404(Mission.objects.prefetch_related("gates"), pk=pk)
    since = int(request.GET.get("since", 0))
    events = [{
        "seq": e.seq, "station": e.station, "station_display": e.get_station_display(),
        "kind": e.kind, "title": e.title, "rationale": e.rationale,
        "alternatives": e.alternatives, "payload": e.payload, "model_name": e.model_name,
        "duration_ms": e.duration_ms, "output_tokens": e.output_tokens,
        "created_at": e.created_at.isoformat(),
    } for e in m.events.filter(seq__gt=since).order_by("seq")]
    return JsonResponse({
        **_mission_summary(m),
        "snapshot_sha256": m.snapshot_sha256, "seed": m.seed, "code_version": m.code_version,
        "prefect_flow_run_id": m.prefect_flow_run_id, "plan": m.plan, "review": m.review,
        "report_page_id": m.report_page_id, "snapshot": _snapshot(m.snapshot),
        "gates": [_gate(g) for g in m.gates.all()],
        "events": events,
    })


@require_POST
def decide_gate(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Log in to the admin to decide gates."}, status=401)
    if not request.user.has_perm("missions.change_gate"):
        return JsonResponse({"error": "You don't have permission to decide gates."}, status=403)
    body = json.loads(request.body or "{}")
    decision = body.get("decision")
    if decision not in (Gate.Status.APPROVED, Gate.Status.REJECTED):
        return JsonResponse({"error": "decision must be 'approved' or 'rejected'"}, status=400)
    updated = Gate.objects.filter(pk=pk, status=Gate.Status.PENDING).update(
        status=decision, decided_at=timezone.now(), decided_by=request.user,
        decided_via=BRIDGE, note=str(body.get("note", ""))[:2000])
    if not updated:
        return JsonResponse({"error": "Gate is not pending."}, status=409)
    return JsonResponse({"gate": _gate(Gate.objects.get(pk=pk))})


def _require_captain(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Log in to the admin first."}, status=401)
    if not request.user.has_perm("missions.add_mission"):
        return JsonResponse({"error": "You don't have permission to launch missions."}, status=403)


def _reconcile():
    """Mark missions whose process has died as failed, so they don't look live forever."""
    from crew import runtime

    if runtime.mission_processes_running():
        return
    # Skip brand-new missions: their process may still be starting
    grace = timezone.now() - timezone.timedelta(seconds=30)
    for m in Mission.objects.filter(status__in=LIVE, created_at__lt=grace):
        rec = MissionRecorder(m)
        rec.log(MissionEvent.Station.SYSTEM, MissionEvent.Kind.ERROR,
                "Mission process is no longer running")
        rec.set_status(Mission.Status.FAILED, finished_at=timezone.now(),
                       verdict="Interrupted: mission process stopped")


@require_GET
def crew_status(request):
    from crew import runtime

    _reconcile()
    active = Mission.objects.filter(status__in=LIVE).first()
    return JsonResponse({
        "models": runtime.list_models(),
        "model_server": runtime.model_status(),
        "active_mission": active.pk if active else None,
        "snapshot": _snapshot(Snapshot.latest_usable()),
        "last_fetch": _last_fetch(),
        "fetching": runtime.ingest_running(),
    })


def _last_fetch():
    s = Snapshot.objects.first()
    return {"at": s.fetched_at.isoformat(), "status": s.status, "error": s.error[:300]} if s else None


@require_POST
def fetch_data(request):
    """Run the archive-ingest Prefect flow now (the same flow the schedule runs)."""
    from crew import runtime

    if denied := _require_captain(request):
        return denied
    if runtime.ingest_running():
        return JsonResponse({"error": "A fetch is already running."}, status=409)
    runtime.launch_ingest()
    return JsonResponse({"fetching": True}, status=202)


@require_POST
def start_model(request):
    from crew import runtime

    if denied := _require_captain(request):
        return denied
    name = json.loads(request.body or "{}").get("model", "")
    if name == runtime.TEST_MODEL:
        return JsonResponse({"error": "The test model needs no server."}, status=400)
    if Mission.objects.filter(status__in=LIVE).exists():
        return JsonResponse({"error": "A mission is running; change models after it ends."}, status=409)
    try:
        runtime.start_model(name)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"model_server": runtime.model_status()})


@require_POST
def stop_model(request):
    from crew import runtime

    if denied := _require_captain(request):
        return denied
    if Mission.objects.filter(status__in=LIVE).exclude(model_name=runtime.TEST_MODEL).exists():
        return JsonResponse({"error": "A mission is using the model."}, status=409)
    runtime.stop_model()
    return JsonResponse({"model_server": runtime.model_status()})


@require_POST
def launch_mission(request):
    from crew import runtime

    if denied := _require_captain(request):
        return denied
    _reconcile()
    if Mission.objects.filter(status__in=LIVE).exists() or runtime.mission_processes_running():
        return JsonResponse({"error": "A mission is already under way. One at a time."}, status=409)
    body = json.loads(request.body or "{}")
    question = str(body.get("question", "")).strip()[:500]
    model = body.get("model", "")
    kind = body.get("kind", Mission.Kind.ANALYSIS)
    if not question:
        return JsonResponse({"error": "Ask the crew a question."}, status=400)
    if kind not in (Mission.Kind.ANALYSIS, Mission.Kind.NEGATIVE_CONTROL):
        return JsonResponse({"error": "Mission type must be analysis or negative_control."}, status=400)
    if model not in {m["name"] for m in runtime.list_models()}:
        return JsonResponse({"error": f"Unknown model: {model}"}, status=400)
    try:
        seed = int(body.get("seed", 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Seed must be a whole number."}, status=400)

    if model != runtime.TEST_MODEL:
        runtime.start_model(model)  # no-op if already serving it
    mission = Mission.objects.create(question=question, kind=kind, seed=seed, model_name=model)
    MissionRecorder(mission).log(
        MissionEvent.Station.CAPTAIN, MissionEvent.Kind.NOTE, "Mission launched from the bridge",
        payload={"by": request.user.get_username(), "model": model, "kind": kind, "seed": seed})
    runtime.launch_mission(mission)
    return JsonResponse({"mission": _mission_summary(mission)}, status=201)
