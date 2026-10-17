import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from missions.models import Gate, Mission, MissionEvent
from missions.recorder import MissionRecorder

DEFAULT_QUESTION = "Is there a gap in the sizes of small planets?"


class Command(BaseCommand):
    help = "Launch an away mission. Every run is logged in the Django admin under Missions."

    def add_arguments(self, parser):
        parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
        parser.add_argument("--negative-control", action="store_true",
                            help="Replace the radii with a unimodal sample; the crew should find nothing")
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--approve-as", default="",
                            help="Pre-approve every gate for an unattended recording, "
                                 "recorded as approved by this name. Without it, the mission "
                                 "waits for approval on the LCARS bridge or in the admin.")
        parser.add_argument("--mission-id", type=int,
                            help="Run a mission already created (by the LCARS bridge)")
        parser.add_argument("--wait-for-model", type=int, default=0, metavar="SECONDS",
                            help="Wait this long for the model server to finish loading")

    def handle(self, question, negative_control, seed, approve_as, mission_id, wait_for_model,
               **options):
        if mission_id:
            mission = Mission.objects.get(pk=mission_id)
        else:
            mission = Mission.objects.create(
                question=question, seed=seed,
                kind=Mission.Kind.NEGATIVE_CONTROL if negative_control else Mission.Kind.ANALYSIS)
        self.stdout.write(f"Mission {mission.pk}, stardate {mission.stardate}: {mission.question}")

        from crew import agents
        if wait_for_model and agents.MODEL_URL != "test":
            self.wait_for_model(mission, agents.MODEL_NAME, wait_for_model)

        policies = {}
        if approve_as:
            via = f"pre-approved for recording by {approve_as}"
            policies = {g: {"decision": Gate.Status.APPROVED, "via": via} for g in Gate.Name.values}
        else:
            self.stdout.write("Gates wait for approval on the LCARS bridge or in the admin")

        from crew.flow import away_mission
        away_mission(mission.pk, gate_policies=policies)
        mission.refresh_from_db()
        self.stdout.write(f"Mission {mission.pk}: {mission.get_status_display()}. {mission.verdict}")

    def wait_for_model(self, mission, name, seconds):
        from crew.runtime import loaded_model

        rec = MissionRecorder(mission)
        rec.log(MissionEvent.Station.SYSTEM, MissionEvent.Kind.NOTE,
                f"Waiting for model server to load {name}")
        start = time.monotonic()
        while time.monotonic() - start < seconds:
            if loaded_model() == name:
                rec.log(MissionEvent.Station.SYSTEM, MissionEvent.Kind.NOTE, f"Model {name} online",
                        duration_ms=int((time.monotonic() - start) * 1000))
                return
            time.sleep(2)
        rec.log(MissionEvent.Station.SYSTEM, MissionEvent.Kind.ERROR,
                f"Model server did not load {name} within {seconds} s")
        rec.set_status(Mission.Status.FAILED, finished_at=timezone.now(),
                       verdict=f"Model {name} did not come online")
        raise CommandError(f"Model {name} did not come online")
