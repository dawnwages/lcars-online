"""DeepEval metrics computed from a mission's event log.

Most are deterministic: they check what the crew did (tool calls, gate order,
numbers), not how its prose sounds. Each test case carries its Mission in
`metadata["mission_id"]`.
"""
import re

from deepeval.metrics import BaseMetric, GEval
from deepeval.models import LocalModel
from deepeval.test_case import LLMTestCase, SingleTurnParams, ToolCall

from crew.agents import MODEL_KEY, MODEL_NAME, MODEL_URL
from missions.models import Gate, Mission, MissionEvent

VALLEY_RANGE = (1.5, 2.1)  # Earth radii; published radius valley (Fulton et al. 2017)


def _tool_args(payload):
    """DeepEval wants a dict; some tools (apply_filters) take a list of filters."""
    args = (payload or {}).get("args") if isinstance(payload, dict) else None
    if args is None or isinstance(args, dict):
        return args
    return {"args": args}


def mission_test_case(mission: Mission) -> LLMTestCase:
    events = list(mission.events.all())
    report = mission.report_page.specific if mission.report_page else None
    report_text = ""
    if report:
        report_text = report.title + "\n" + report.intro + "\n" + " ".join(
            re.sub("<[^>]+>", "", str(b.value)) for b in report.body)
    return LLMTestCase(
        name=f"mission-{mission.pk}",
        input=mission.question,
        actual_output=report_text or mission.verdict or "(no report)",
        context=[str(mission.result)],
        tools_called=[ToolCall(name=e.title, input_parameters=_tool_args(e.payload))
                      for e in events if e.kind == MissionEvent.Kind.TOOL_CALL],
        metadata={"mission_id": mission.pk},
    )


class _MissionMetric(BaseMetric):
    threshold = 1.0
    async_mode = False

    def __init__(self):
        self.score = 0
        self.success = False
        self.reason = ""

    def mission(self, test_case):
        return Mission.objects.get(pk=test_case.metadata["mission_id"])

    def a_measure(self, test_case, *args, **kwargs):
        return self.measure(test_case)

    def is_successful(self):
        return bool(self.success)

    def _done(self, ok, reason):
        self.score, self.success, self.reason = (1.0 if ok else 0.0), ok, reason
        return self.score


class PlanPreregistered(_MissionMetric):
    """The plan was approved before Engineering computed anything."""

    @property
    def __name__(self):
        return "Plan pre-registered"

    def measure(self, test_case, *args, **kwargs):
        m = self.mission(test_case)
        approved = m.events.filter(station=MissionEvent.Station.CAPTAIN, kind=MissionEvent.Kind.GATE,
                                   title__startswith=Gate.Name.PLAN.label).first()
        first_compute = m.events.filter(station=MissionEvent.Station.ENGINEERING,
                                        kind=MissionEvent.Kind.TOOL_CALL).first()
        ok = bool(approved and first_compute and approved.seq < first_compute.seq
                  and approved.title.endswith("approved"))
        return self._done(ok, f"plan approval seq={getattr(approved, 'seq', None)}, "
                              f"first computation seq={getattr(first_compute, 'seq', None)}")


class ValleyRecovered(_MissionMetric):
    """Analysis missions find a significant valley inside the published range."""

    @property
    def __name__(self):
        return "Radius valley recovered"

    def measure(self, test_case, *args, **kwargs):
        m = self.mission(test_case)
        a = (m.result or {}).get("analyze_radius_distribution") or {}
        valley = a.get("valley") or {}
        p = (a.get("silverman") or {}).get("p_value")
        alpha = (m.plan or {}).get("significance_level", 0.05)
        loc = valley.get("radius_earth")
        ok = loc is not None and VALLEY_RANGE[0] <= loc <= VALLEY_RANGE[1] and p is not None and p < alpha
        return self._done(ok, f"valley={loc} R_earth, p={p}, alpha={alpha}")


class NegativeControlNull(_MissionMetric):
    """On unimodal data the crew must not claim a valley."""

    @property
    def __name__(self):
        return "Negative control finds nothing"

    def measure(self, test_case, *args, **kwargs):
        m = self.mission(test_case)
        a = (m.result or {}).get("analyze_radius_distribution") or {}
        p = (a.get("silverman") or {}).get("p_value")
        alpha = (m.plan or {}).get("significance_level", 0.05)
        verdict = (m.review or {}).get("verdict")
        ok = p is not None and p >= alpha
        return self._done(ok, f"p={p} (alpha={alpha}), Tactical verdict={verdict}")


class ReportNumbersFaithful(_MissionMetric):
    """Every decimal number in the Captain's Log appears in Engineering's results."""

    @property
    def __name__(self):
        return "Report numbers come from results"

    def measure(self, test_case, *args, **kwargs):
        # The heading's stardate is the mission's date, not a result
        text = test_case.actual_output.replace(self.mission(test_case).stardate, "")
        numbers = set(re.findall(r"\d+\.\d+", text))
        source = str(test_case.context)
        missing = sorted(n for n in numbers if n not in source)
        if not numbers:
            return self._done(False, "the report cites no statistics (no p-value, valley or interval)")
        return self._done(not missing, f"{len(numbers)} numbers; not found in results: {missing or 'none'}")


class SampleChecked(_MissionMetric):
    """The Science Officer checked the sample size before committing to a plan."""

    @property
    def __name__(self):
        return "Sample size checked before planning"

    def measure(self, test_case, *args, **kwargs):
        m = self.mission(test_case)
        ok = m.events.filter(station=MissionEvent.Station.SCIENCE, title="count_population",
                             kind=MissionEvent.Kind.TOOL_CALL).exists()
        return self._done(ok, "count_population called" if ok else "never checked n")


def judge():
    """The local model as judge. Same model as the crew: treat as a secondary signal."""
    return LocalModel(model=MODEL_NAME, base_url=MODEL_URL, api_key=MODEL_KEY, temperature=0)


def rigor_metric():
    return GEval(
        name="Analytic rigor of the report",
        evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.CONTEXT],
        evaluation_steps=[
            "Check the report states the finding with an uncertainty interval or p-value.",
            "Check it says how the planet population was chosen and why.",
            "Check it reports whether the result holds across the precision-cut sweep in the context.",
            "Check it states limitations and does not claim more than the context supports.",
        ],
        model=judge(), threshold=0.6, async_mode=False)
