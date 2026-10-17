"""The crew: one narrow PydanticAI agent per station, each with its own tools."""
import os
from dataclasses import dataclass, field

import pandas as pd
from pydantic_ai import Agent, ModelRetry, NativeOutput, PromptedOutput, RunContext, ToolOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from crew import science
from crew.schemas import AnalysisPlan, CaptainsLog, OpsBrief, PopulationFilter, Review
from missions.models import MissionEvent
from missions.recorder import MissionRecorder

# A local OpenAI-compatible server (llama.cpp's llama-server). See README.
MODEL_URL = os.environ.get("CREW_MODEL_URL", "http://127.0.0.1:8089/v1")
MODEL_NAME = "test" if MODEL_URL == "test" else os.environ.get("CREW_MODEL", "local")
MODEL_KEY = os.environ.get("CREW_MODEL_KEY", "lcars-local")
OUTPUT_MODE = os.environ.get("CREW_OUTPUT_MODE", "tool")  # tool | native | prompted (llama.cpp can't combine native with tools)
TEMPERATURE = float(os.environ.get("CREW_TEMPERATURE", "0.2"))

OUTPUT_WRAPPERS = {"native": NativeOutput, "tool": ToolOutput, "prompted": PromptedOutput}


def make_model():
    if MODEL_URL == "test":
        # Schema-valid random output, for testing the flow without a model server
        from pydantic_ai.models.test import TestModel
        return TestModel(seed=0)
    return OpenAIChatModel(
        MODEL_NAME, provider=OpenAIProvider(base_url=MODEL_URL, api_key=MODEL_KEY),
        settings={"temperature": TEMPERATURE, "seed": 0})


@dataclass
class CrewDeps:
    recorder: MissionRecorder
    df: pd.DataFrame
    # Ops' hazards with IDs ({"id", "name", "implication"}); every plan must answer each one
    hazards: list = field(default_factory=list)


def number_hazards(brief):
    """Give Ops' hazards stable IDs (H1, H2, ...) for the plan to answer."""
    return [{"id": f"H{i}", "name": h.name, "evidence": h.evidence, "implication": h.implication}
            for i, h in enumerate(brief.hazards, start=1)]


def hazard_checklist(hazards):
    lines = [f"{h['id']}. {h['name']}: {h['evidence']}. Implication: {h['implication']}"
             for h in hazards]
    return ("Hazard checklist. Your plan's hazard_responses must answer EVERY item, once each:\n"
            + "\n".join(lines))


# The analysis variable itself; Engineering already restricts it to science.WINDOW
ANALYSIS_COLUMN = "pl_rade"


def hazard_problems(plan, hazards):
    """What's wrong with a plan's hazard responses. Empty means every hazard is answered."""
    problems = []
    ids = {h["id"]: h for h in hazards}
    answered = {}
    for r in plan.hazard_responses:
        if r.hazard_id not in ids:
            problems.append(f"{r.hazard_id} is not on the checklist (valid IDs: {', '.join(ids)}).")
            continue
        if r.hazard_id in answered:
            problems.append(f"{r.hazard_id} is answered more than once; give one response.")
        answered[r.hazard_id] = r
        name = ids[r.hazard_id]["name"]
        if r.response == "filter":
            n = r.filter_number
            if n is None or not 1 <= n <= len(plan.population):
                problems.append(f"{r.hazard_id} ({name}) says 'filter' but filter_number {n} is not "
                                f"one of your {len(plan.population)} population filters.")
            elif plan.population[n - 1].column == ANALYSIS_COLUMN:
                problems.append(
                    f"{r.hazard_id} ({name}) points to a filter on {ANALYSIS_COLUMN}, the variable "
                    f"being analyzed; Engineering already applies the {science.WINDOW[0]}-"
                    f"{science.WINDOW[1]} Earth-radius window, so that filter does not address a "
                    "data hazard. Filter on the column the hazard is about, or accept the risk.")
        elif len(r.explanation.strip()) < 40:
            problems.append(f"{r.hazard_id} ({name}) accepts the risk without a real explanation; "
                            "say why it can't or needn't be handled.")
    for hid, h in ids.items():
        if hid not in answered:
            problems.append(f"{hid} ({h['name']}) has no response. Add a population filter that "
                            "handles it, or accept the risk and explain why.")
    return problems


def _agent(name, output_type, instructions, tools=(), capabilities=()):
    return Agent(
        make_model(), name=name, deps_type=CrewDeps, retries=3,
        output_type=OUTPUT_WRAPPERS[OUTPUT_MODE](output_type),
        instructions=instructions, tools=list(tools), capabilities=list(capabilities))


# Tools. Each one logs its call and result to the mission.

def count_population(ctx: RunContext[CrewDeps], filters: list[PopulationFilter]) -> dict:
    """Count how many planets remain after applying filters in order, step by step."""
    args = [f.model_dump(exclude={"reason"}) for f in filters]
    with ctx.deps.recorder.tool(ctx.deps.recorder.current_station, "count_population", args) as box:
        _, steps = science.apply_filters(ctx.deps.df, args)
        box["result"] = {"steps": steps, "final_n": steps[-1]["after"] if steps else len(ctx.deps.df)}
    return box["result"]


def column_summary(ctx: RunContext[CrewDeps], column: str) -> dict:
    """Missing values, quantiles or top values for one column of the planet table."""
    df = ctx.deps.df
    with ctx.deps.recorder.tool(ctx.deps.recorder.current_station, "column_summary", {"column": column}) as box:
        if column not in df.columns:
            box["result"] = {"error": f"unknown column {column}", "columns": list(df.columns)}
        else:
            s = df[column]
            summary = {"column": column, "missing_pct": round(float(s.isna().mean() * 100), 1)}
            if pd.api.types.is_numeric_dtype(s):
                summary["quantiles"] = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).round(4).to_dict()
            else:
                summary["top_values"] = s.value_counts().head(8).to_dict()
            box["result"] = summary
    return box["result"]


OPS = """You are Ops on a starship science team. You audit a dataset before anyone analyzes it.
From the data card, report what the data is, what changed since the previous snapshot
(new, removed and revised planets), and every hazard an analyst must handle:
selection effects, inferred (not measured) values, missing data, measurement precision.
Quote the numbers from the data card as evidence. Do not analyze or draw conclusions."""

SCIENCE = """You are the Science Officer. You write an analysis plan BEFORE any results exist.
The plan is approved by the captain and then executed exactly, so choose carefully:
- Pick the population with filters. Use count_population to check the sample stays large
  enough for the test to have power, and column_summary to inspect columns.
- The method is fixed: a kernel density estimate of log10(planet radius) between 1 and 4
  Earth radii, Silverman's bandwidth test for more than one mode, and a bootstrap interval
  for the valley location. You choose the population, the bandwidth and the significance level.
- Name the result that would falsify the hypothesis, alternatives you rejected and why,
  and the risks to the conclusion.
- Answer every item on the hazard checklist in hazard_responses: either point to the
  population filter that handles it, or accept the risk and explain why. Unanswered hazards
  are sent back to you.
Engineering will also always run a sweep of precision cuts and a negative control."""

TACTICAL = """You are Tactical, the adversarial reviewer. Your job is to find reasons NOT to
believe the result. Check for: selection bias from discovery method, circular use of
inferred values, choosing filters after seeing results (p-hacking), low power, measurement
error, and whether the conclusion holds across the whole precision-cut sweep or only at one
setting. The negative control must find no valley; if it does, the method is broken.
Accept only if the conclusion survives. Ask for revision if a fixable flaw remains."""

LOG = """You write the Captain's Log: a short public report of the mission for data
scientists. State the finding with its numbers and uncertainty, how the population was
chosen, what the reviewer raised, and the limitations. No hype; never claim more than the
evidence supports. Write in the first person plural ("we")."""


def check_plan_hazards(ctx: RunContext[CrewDeps], plan: AnalysisPlan) -> AnalysisPlan:
    """Enforced in code: a plan that leaves a hazard unanswered goes back to the model."""
    problems = hazard_problems(plan, ctx.deps.hazards)
    if problems:
        ctx.deps.recorder.log(MissionEvent.Station.SCIENCE, MissionEvent.Kind.NOTE,
                              "Plan returned: hazards not answered",
                              rationale="\n".join(problems), payload=plan.model_dump())
        raise ModelRetry("Revise the plan. " + " ".join(problems))
    return plan


def build_crew(capabilities=()):
    science_officer = _agent("science_officer", AnalysisPlan, SCIENCE,
                             tools=[count_population, column_summary], capabilities=capabilities)
    science_officer.output_validator(check_plan_hazards)
    return {
        "ops": _agent("ops", OpsBrief, OPS, capabilities=capabilities),
        "science": science_officer,
        "tactical": _agent("tactical", Review, TACTICAL, tools=[count_population],
                           capabilities=capabilities),
        "log": _agent("captains_log", CaptainsLog, LOG, capabilities=capabilities),
    }


def run_station(agent, station, prompt, deps: CrewDeps):
    """Run one agent and log its output, token use and timing to the mission."""
    import time

    deps.recorder.current_station = station
    start = time.monotonic()
    result = agent.run_sync(prompt, deps=deps)
    usage = result.usage
    deps.recorder.log(
        station, MissionEvent.Kind.MODEL_OUTPUT, f"{agent.name} output",
        payload=result.output.model_dump(), model_name=MODEL_NAME,
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        duration_ms=int((time.monotonic() - start) * 1000))
    return result.output
