import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import Gate, Mission
from .recorder import MissionRecorder


class MissionAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mission = Mission.objects.create(question="Is there a gap?")
        rec = MissionRecorder(cls.mission)
        rec.log("ops", "tool_call", "load_snapshot")
        rec.log("system", "gate", "Waiting for approval: Approve analysis plan",
                payload={"hypothesis": "There is a valley"})
        cls.gate = Gate.objects.create(mission=cls.mission, name=Gate.Name.PLAN)
        User = get_user_model()
        cls.captain = User.objects.create_superuser("picard", "p@example.com", "engage")
        cls.ensign = User.objects.create_user("wesley", "w@example.com", "shutup")

    def decide(self, client, decision="approved", gate=None):
        return client.post(f"/api/gates/{(gate or self.gate).pk}/decide/",
                           json.dumps({"decision": decision, "note": "Make it so"}),
                           content_type="application/json")

    def test_list_and_detail(self):
        data = self.client.get("/api/missions/").json()
        self.assertEqual(data["missions"][0]["pending_gates"], 1)
        detail = self.client.get(f"/api/missions/{self.mission.pk}/").json()
        self.assertEqual([e["seq"] for e in detail["events"]], [1, 2])
        self.assertEqual(detail["gates"][0]["summary"], {"hypothesis": "There is a valley"})

    def test_since_returns_only_new_events(self):
        detail = self.client.get(f"/api/missions/{self.mission.pk}/?since=1").json()
        self.assertEqual([e["seq"] for e in detail["events"]], [2])

    def test_deciding_requires_login(self):
        self.assertEqual(self.decide(self.client).status_code, 401)

    def test_deciding_requires_permission(self):
        self.client.force_login(self.ensign)
        self.assertEqual(self.decide(self.client).status_code, 403)

    def test_deciding_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.captain)
        self.assertEqual(self.decide(client).status_code, 403)
        token = client.get("/api/missions/session/").json()["csrf_token"]
        response = client.post(f"/api/gates/{self.gate.pk}/decide/",
                               json.dumps({"decision": "approved"}),
                               content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    def test_decision_is_recorded_and_final(self):
        self.client.force_login(self.captain)
        gate = self.decide(self.client).json()["gate"]
        self.assertEqual((gate["status"], gate["decided_via"], gate["decided_by"]),
                         ("approved", "LCARS bridge", "picard"))
        self.assertEqual(self.decide(self.client, "rejected").status_code, 409)

    def test_cors_allows_credentials_for_the_bridge(self):
        response = self.client.get("/api/missions/", HTTP_ORIGIN="http://localhost:8080")
        self.assertEqual(response["access-control-allow-credentials"], "true")


class LaunchAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.captain = User.objects.create_superuser("picard", "p@example.com", "engage")
        cls.ensign = User.objects.create_user("wesley", "w@example.com", "shutup")

    def setUp(self):
        from unittest import mock
        patches = [
            mock.patch("crew.runtime.launch_mission", return_value=123),
            mock.patch("crew.runtime.start_model"),
            mock.patch("crew.runtime.mission_processes_running", return_value=False),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def launch(self, **body):
        payload = {"question": "Is there a gap?", "model": "test", "kind": "analysis", **body}
        return self.client.post("/api/missions/launch/", json.dumps(payload),
                                content_type="application/json")

    def test_launch_requires_login_and_permission(self):
        self.assertEqual(self.launch().status_code, 401)
        self.client.force_login(self.ensign)
        self.assertEqual(self.launch().status_code, 403)

    def test_launch_creates_and_starts_a_mission(self):
        self.client.force_login(self.captain)
        response = self.launch()
        self.assertEqual(response.status_code, 201)
        mission = Mission.objects.get(pk=response.json()["mission"]["id"])
        self.assertEqual(mission.model_name, "test")
        self.assertEqual(mission.events.first().title, "Mission launched from the bridge")
        self.mocks[0].assert_called_once()   # process launched
        self.mocks[1].assert_not_called()    # test model needs no server

    def test_real_model_starts_its_server(self):
        from unittest import mock
        self.client.force_login(self.captain)
        with mock.patch("crew.runtime.list_models", return_value=[{"name": "Qwen"}, {"name": "test"}]):
            self.assertEqual(self.launch(model="Qwen").status_code, 201)
        self.mocks[1].assert_called_once_with("Qwen")

    def test_one_mission_at_a_time(self):
        self.client.force_login(self.captain)
        self.assertEqual(self.launch().status_code, 201)
        self.assertEqual(self.launch().status_code, 409)

    def test_rejects_unknown_model_and_kind(self):
        self.client.force_login(self.captain)
        self.assertEqual(self.launch(model="../../etc/passwd").status_code, 400)
        self.assertEqual(self.launch(kind="red_team").status_code, 400)

    def test_dead_missions_are_marked_failed(self):
        from django.utils import timezone
        stale = Mission.objects.create(question="Old", status=Mission.Status.RUNNING,
                                       created_at=timezone.now() - timezone.timedelta(minutes=5))
        self.client.get("/api/crew/status/")
        stale.refresh_from_db()
        self.assertEqual(stale.status, Mission.Status.FAILED)


class FetchDataAPITests(TestCase):
    def test_fetch_requires_login_and_runs_once_at_a_time(self):
        from unittest import mock
        captain = get_user_model().objects.create_superuser("picard", "p@example.com", "engage")
        with mock.patch("crew.runtime.launch_ingest") as launch, \
                mock.patch("crew.runtime.ingest_running", return_value=False):
            self.assertEqual(self.client.post("/api/crew/fetch/").status_code, 401)
            self.client.force_login(captain)
            self.assertEqual(self.client.post("/api/crew/fetch/").status_code, 202)
            launch.assert_called_once()
        with mock.patch("crew.runtime.ingest_running", return_value=True):
            self.assertEqual(self.client.post("/api/crew/fetch/").status_code, 409)
