"""Write mission events, and enforce approval gates, from crew code."""
import time
from contextlib import contextmanager

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Gate, Mission, MissionEvent


class GateRejected(Exception):
    pass


class MissionRecorder:
    def __init__(self, mission: Mission):
        self.mission = mission
        self.current_station = MissionEvent.Station.SYSTEM

    @transaction.atomic
    def log(self, station, kind, title, *, rationale="", alternatives=None, payload=None,
            model_name="", input_tokens=None, output_tokens=None, duration_ms=None):
        last = (MissionEvent.objects.select_for_update().filter(mission=self.mission)
                .aggregate(m=Max("seq"))["m"]) or 0
        return MissionEvent.objects.create(
            mission=self.mission, seq=last + 1, station=station, kind=kind, title=title[:300],
            rationale=rationale, alternatives=alternatives or [], payload=payload,
            model_name=model_name, input_tokens=input_tokens, output_tokens=output_tokens,
            duration_ms=duration_ms)

    @contextmanager
    def tool(self, station, name, args):
        """Log a deterministic tool call and its result, with timing."""
        self.log(station, MissionEvent.Kind.TOOL_CALL, name, payload={"args": args})
        start = time.monotonic()
        box = {}
        try:
            yield box
        except Exception as exc:
            self.log(station, MissionEvent.Kind.ERROR, f"{name} failed: {exc}")
            raise
        self.log(station, MissionEvent.Kind.TOOL_RESULT, name, payload=box.get("result"),
                 duration_ms=int((time.monotonic() - start) * 1000))

    def set_status(self, status, **fields):
        for k, v in fields.items():
            setattr(self.mission, k, v)
        self.mission.status = status
        self.mission.save()

    def request_gate(self, name, summary, *, policy=None):
        """Open an approval gate and block until it is decided.

        Without a policy, a person decides in the admin. A policy decides
        automatically for unattended runs: {"decision": "approved" | "rejected",
        "via": "pre-approved for recording by Dawn"}. Either way it is logged.
        """
        gate, _ = Gate.objects.get_or_create(mission=self.mission, name=name)
        self.log(MissionEvent.Station.SYSTEM, MissionEvent.Kind.GATE,
                 f"Waiting for approval: {gate.get_name_display()}", payload=summary)
        if policy:
            gate.status = policy["decision"]
            gate.decided_at = timezone.now()
            gate.decided_via = policy["via"]
            gate.save()
        else:
            self.set_status(Mission.Status.AWAITING_APPROVAL)
            while gate.status == Gate.Status.PENDING:
                time.sleep(2)
                gate.refresh_from_db()
        self.log(MissionEvent.Station.CAPTAIN, MissionEvent.Kind.GATE,
                 f"{gate.get_name_display()}: {gate.status}",
                 rationale=gate.note, payload={"decided_via": gate.decided_via,
                                               "decided_by": str(gate.decided_by or "")})
        if gate.status == Gate.Status.REJECTED:
            self.set_status(Mission.Status.REJECTED, finished_at=timezone.now())
            raise GateRejected(gate.note or gate.get_name_display())
        self.set_status(Mission.Status.RUNNING)
        return gate
