"""Grade the most recent completed missions.

    uv run deepeval test run evals/test_missions.py
Set EVAL_SKIP_JUDGE=1 to run only the deterministic metrics (no model server needed).
"""
import os

import pytest
from deepeval import assert_test

from evals.mission_metrics import (NegativeControlNull, PlanPreregistered, ReportNumbersFaithful,
                                   SampleChecked, ValleyRecovered, mission_test_case, rigor_metric)
from missions.models import Mission

LIMIT = int(os.environ.get("EVAL_MISSIONS", "5"))
JUDGE = not os.environ.get("EVAL_SKIP_JUDGE")


# Missions run without a real model: "test" (random output) and "local" (early test runs,
# recorded before test-model missions were labeled)
NOT_REAL_MODELS = ["test", "local", ""]


def recent(kind):
    return list(Mission.objects.filter(kind=kind, status=Mission.Status.COMPLETE)
                .exclude(model_name__in=NOT_REAL_MODELS)[:LIMIT])


@pytest.mark.parametrize("mission", recent(Mission.Kind.ANALYSIS), ids=lambda m: f"mission-{m.pk}")
def test_analysis_mission(mission):
    metrics = [PlanPreregistered(), SampleChecked(), ValleyRecovered(), ReportNumbersFaithful()]
    if JUDGE:
        metrics.append(rigor_metric())
    assert_test(mission_test_case(mission), metrics)


@pytest.mark.parametrize("mission", recent(Mission.Kind.NEGATIVE_CONTROL),
                         ids=lambda m: f"mission-{m.pk}")
def test_negative_control_mission(mission):
    assert_test(mission_test_case(mission), [PlanPreregistered(), NegativeControlNull()])
