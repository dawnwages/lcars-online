import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase

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


class HazardCheckTests(TestCase):
    """A plan must answer every hazard Ops raised; this is enforced in code."""

    HAZARDS = [
        {"id": "H1", "name": "Discovery-method selection bias", "evidence": "median period 8 d vs 305 d",
         "implication": "Restrict or compare by discovery method"},
        {"id": "H2", "name": "Inferred masses", "evidence": "47% from M-R relation",
         "implication": "Don't use mass as if measured"},
    ]

    def plan(self, population, responses):
        from crew.schemas import AnalysisPlan
        return AnalysisPlan(
            hypothesis="Two populations", null_hypothesis="One population",
            population=population, bandwidth_dex=0.04, significance_level=0.05,
            falsification="Silverman p >= 0.05 across the precision sweep",
            alternatives_considered=[{"option": "All methods", "why_not": "mixes selection effects"}],
            risks=["Small sample"], hazard_responses=responses)

    def test_qwen_bakeoff_plan_is_rejected(self):
        # The plan Qwen3.5-9B produced in all three bake-off runs, now with token responses
        from crew.agents import hazard_problems
        plan = self.plan(
            [{"column": "pl_rade", "op": "ge", "value": 1.0, "reason": "window"},
             {"column": "pl_rade", "op": "le", "value": 4.0, "reason": "window"}],
            [{"hazard_id": "H1", "response": "filter", "filter_number": 1, "explanation": "window"}])
        problems = hazard_problems(plan, self.HAZARDS)
        self.assertTrue(any("variable being analyzed" in p for p in problems))
        self.assertTrue(any(p.startswith("H2") and "no response" in p for p in problems))

    def test_plan_answering_every_hazard_passes(self):
        from crew.agents import hazard_problems
        plan = self.plan(
            [{"column": "disc_method", "op": "eq", "value": "tran", "reason": "one selection function"}],
            [{"hazard_id": "H1", "response": "filter", "filter_number": 1,
              "explanation": "Transit only, so one detection bias"},
             {"hazard_id": "H2", "response": "accept_risk", "filter_number": None,
              "explanation": "The analysis uses radius only, so inferred masses never enter it"}])
        self.assertEqual(hazard_problems(plan, self.HAZARDS), [])

    def test_bad_responses_are_named(self):
        from crew.agents import hazard_problems
        plan = self.plan(
            [{"column": "disc_method", "op": "eq", "value": "tran", "reason": "x"}],
            [{"hazard_id": "H1", "response": "filter", "filter_number": 5, "explanation": "x"},
             {"hazard_id": "H2", "response": "accept_risk", "explanation": "n/a"},
             {"hazard_id": "H9", "response": "accept_risk", "explanation": "made-up hazard " * 4}])
        problems = " ".join(hazard_problems(plan, self.HAZARDS))
        self.assertIn("filter_number 5", problems)
        self.assertIn("without a real explanation", problems)
        self.assertIn("H9 is not on the checklist", problems)



class HazardRetryTests(TransactionTestCase):
    """Real transactions: PydanticAI runs the validator in a worker thread that logs to the DB."""

    HAZARDS = HazardCheckTests.HAZARDS
    plan = HazardCheckTests.plan

    def test_science_officer_is_sent_back_until_hazards_are_answered(self):
        """End to end with a scripted model: first plan ignores H2, the retry fixes it."""
        import pandas as pd
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from crew import agents, science

        bad = {"hazard_id": "H1", "response": "filter", "filter_number": 1, "explanation": "transit"}
        good = {"hazard_id": "H2", "response": "accept_risk",
                "explanation": "Only radius is analyzed, so inferred masses never enter it"}
        base = self.plan([{"column": "disc_method", "op": "eq", "value": "tran", "reason": "x"}],
                         [bad]).model_dump()
        calls = []

        def scripted(messages, info):
            calls.append(1)
            responses = [bad] if len(calls) == 1 else [bad, good]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                     {**base, "hazard_responses": responses})])

        mission = Mission.objects.create(question="Gap?")
        deps = agents.CrewDeps(recorder=MissionRecorder(mission), df=pd.DataFrame(),
                               hazards=self.HAZARDS)
        crew = agents.build_crew()
        with crew["science"].override(model=FunctionModel(scripted)):
            plan = crew["science"].run_sync("Plan it", deps=deps).output
        self.assertEqual(len(calls), 2)
        self.assertEqual({r.hazard_id for r in plan.hazard_responses}, {"H1", "H2"})
        returned = mission.events.get(title="Plan returned: hazards not answered")
        self.assertIn("H2", returned.rationale)


class StationLimitTests(TransactionTestCase):
    def test_runaway_tool_calls_are_stopped_and_logged(self):
        """A planner that keeps calling tools (as Qwen did, 16 times) hits its budget."""
        from pydantic_ai.exceptions import AgentRunError
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        from crew import agents, science

        def flailing(messages, info):
            return ModelResponse(parts=[ToolCallPart("column_summary", {"column": "pl_rade"})])

        df, _ = science.load_snapshot()
        mission = Mission.objects.create(question="Gap?")
        deps = agents.CrewDeps(recorder=MissionRecorder(mission), df=df, hazards=[])
        crew = agents.build_crew()
        with crew["science"].override(model=FunctionModel(flailing)):
            with self.assertRaises(AgentRunError):
                agents.run_station(crew["science"], "science", "Plan it", deps)
        error = mission.events.get(kind="error")
        self.assertIn("science_officer failed", error.title)
        calls = error.payload["tool_calls"]
        self.assertLessEqual(calls.count("column_summary"), 7)
        self.assertGreater(error.payload["model_requests"], 1)
