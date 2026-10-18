"""The crew: one narrow PydanticAI agent per station, each with its own tools."""
import os
import re
from dataclasses import dataclass, field

import pandas as pd
from openai import AsyncOpenAI
from pydantic_ai import (Agent, ModelRetry, NativeOutput, PromptedOutput, RunContext, ToolOutput,
                         capture_run_messages)
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.usage import UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from crew import science
from crew.models import MODEL_PROFILES
from crew.schemas import AnalysisPlan, CaptainsLog, OpsBrief, PopulationFilter, Review
from missions.models import MissionEvent
from missions.recorder import MissionRecorder

# A local OpenAI-compatible server (llama.cpp's llama-server). See README.
MODEL_URL = os.environ.get("CREW_MODEL_URL", "http://127.0.0.1:8089/v1")
MODEL_NAME = "test" if MODEL_URL == "test" else os.environ.get("CREW_MODEL", "local")
MODEL_KEY = os.environ.get("CREW_MODEL_KEY", "lcars-local")
OUTPUT_MODE = os.environ.get("CREW_OUTPUT_MODE", "tool")  # tool | native | prompted (llama.cpp can't combine native with tools)
TEMPERATURE = float(os.environ.get("CREW_TEMPERATURE", "0.2"))
# Small local models can loop on long structured output; fail fast instead of for minutes
MAX_TOKENS = int(os.environ.get("CREW_MAX_TOKENS")
                 or MODEL_PROFILES.get(MODEL_NAME, {}).get("max_tokens", 1500))
REQUEST_TIMEOUT = float(os.environ.get("CREW_REQUEST_TIMEOUT", "240"))

# Per-station budget for one run: model requests (incl. retries) and tool calls
STATION_LIMITS = {
    "ops": UsageLimits(request_limit=4),
    "science": UsageLimits(request_limit=16, tool_calls_limit=10),
    # Room to re-count the population under alternative filters (e.g. transit only)
    "tactical": UsageLimits(request_limit=12, tool_calls_limit=8),
    "log": UsageLimits(request_limit=4),
}

OUTPUT_WRAPPERS = {"native": NativeOutput, "tool": ToolOutput, "prompted": PromptedOutput}


def make_model():
    if MODEL_URL == "test":
        # Schema-valid random output, for testing the flow without a model server
        from pydantic_ai.models.test import TestModel
        return TestModel(seed=0)
    # No silent client retries: a timed-out request would otherwise run up to three times
    client = AsyncOpenAI(base_url=MODEL_URL, api_key=MODEL_KEY, timeout=REQUEST_TIMEOUT, max_retries=0)
    return OpenAIChatModel(
        MODEL_NAME, provider=OpenAIProvider(openai_client=client),
        settings={"temperature": TEMPERATURE, "seed": 0, "max_tokens": MAX_TOKENS})


@dataclass
class CrewDeps:
    recorder: MissionRecorder
    df: pd.DataFrame
    # Ops' hazards with IDs ({"id", "name", "implication"}); every plan must answer each one
    hazards: list = field(default_factory=list)
    # Text whose numbers a review may cite: results, the data card, and counts it ran
    evidence: list = field(default_factory=list)


def number_hazards(brief):
    """Give Ops' hazards stable IDs (H1, H2, ...) for the plan to answer."""
    return [{"id": f"H{i}", "name": h.name, "evidence": h.evidence, "implication": h.implication}
            for i, h in enumerate(brief.hazards, start=1)]


def planning_facts(card):
    """The data card facts a planner needs, so it doesn't spend tool calls rediscovering them."""
    keys = ["n_planets", "discovery_methods", "missing_pct", "mass_provenance",
            "median_orbital_period_days_by_method", "radius_relative_error_quantiles",
            "changes_since_previous_snapshot"]
    lines = [f"- {k}: {card[k]}" for k in keys if k in card]
    return ("Data facts (from Ops' data card; rade_rel_err = radius error / radius):\n"
            + "\n".join(lines))


def hazard_checklist(hazards):
    lines = [f"{h['id']}. {h['name']}: {h['evidence']}. Implication: {h['implication']}"
             for h in hazards]
    return ("Hazard checklist. Your plan's hazard_responses must answer EVERY item, once each:\n"
            + "\n".join(lines))


# The analysis variable itself; Engineering already restricts it to science.WINDOW
ANALYSIS_COLUMN = "pl_rade"
# Columns the fixed method never uses: filtering on them can't address a hazard to this
# analysis, and only costs planets (and adds its own selection)
UNUSED_BY_METHOD = {"pl_bmasse", "pl_bmasseerr1", "pl_bmasseerr2", "pl_bmassprov"}


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
                choices = "; ".join(f"{i} = {f.column} {f.op} {'' if f.value is None else f.value}".strip()
                                    for i, f in enumerate(plan.population, start=1))
                problems.append(f"{r.hazard_id} ({name}) says 'filter' but filter_number is {n}. Set "
                                f"filter_number to the position of the filter that handles it ({choices}), "
                                "or use response 'accept_risk' with an explanation.")
            elif plan.population[n - 1].column == ANALYSIS_COLUMN:
                problems.append(
                    f"{r.hazard_id} ({name}) points to a filter on {ANALYSIS_COLUMN}, the variable "
                    f"being analyzed; Engineering already applies the {science.WINDOW[0]}-"
                    f"{science.WINDOW[1]} Earth-radius window, so that filter does not address a "
                    "data hazard. Filter on the column the hazard is about, or accept the risk.")
            elif plan.population[n - 1].column in UNUSED_BY_METHOD:
                problems.append(
                    f"{r.hazard_id} ({name}) points to a filter on {plan.population[n - 1].column}, "
                    "which this method never uses (it analyzes planet radius only). That filter "
                    "removes planets and adds its own selection without protecting this analysis. "
                    "Drop it and mark the hazard 'not_applicable' with the reason.")
        elif len(r.explanation.strip()) < 40:
            what = "accepts the risk" if r.response == "accept_risk" else "says not applicable"
            problems.append(f"{r.hazard_id} ({name}) {what} without a real explanation; "
                            "say why in a sentence.")
    for hid, h in ids.items():
        if hid not in answered:
            problems.append(f"{hid} ({h['name']}) has no response. Add a population filter that "
                            "handles it, or accept the risk and explain why.")
    return problems


def _agent(name, output_type, instructions, tools=(), capabilities=(), retries=3):
    return Agent(
        make_model(), name=name, deps_type=CrewDeps, retries=retries,
        output_type=OUTPUT_WRAPPERS[OUTPUT_MODE](output_type),
        instructions=instructions, tools=list(tools), capabilities=list(capabilities))


# Tools. Each one logs its call and result to the mission.

def count_population(ctx: RunContext[CrewDeps], filters: list[PopulationFilter]) -> dict:
    """Count how many planets remain after applying filters in order, step by step."""
    args = [f.model_dump(exclude={"reason"}) for f in filters]
    with ctx.deps.recorder.tool(ctx.deps.recorder.current_station, "count_population", args) as box:
        try:
            _, steps = science.apply_filters(ctx.deps.df, args)
            box["result"] = {"steps": steps,
                             "final_n": steps[-1]["after"] if steps else len(ctx.deps.df)}
            ctx.deps.evidence.append(str(box["result"]))
        except science.InvalidFilter as exc:
            # Tell the model what's wrong, so it can fix the filter
            box["result"] = {"error": str(exc)}
    return box["result"]


def breakdown_population(ctx: RunContext[CrewDeps], filters: list[PopulationFilter],
                         by: str) -> dict:
    """Apply filters, then count the remaining planets in every group of one column at once.

    Text columns (e.g. disc_method) are counted per value; numeric columns (e.g. pl_orbper)
    per quartile range. Use this instead of one count_population call per group.
    """
    args = {"filters": [f.model_dump(exclude={"reason"}) for f in filters], "by": by}
    with ctx.deps.recorder.tool(ctx.deps.recorder.current_station, "breakdown_population", args) as box:
        try:
            subset, steps = science.apply_filters(ctx.deps.df, args["filters"])
            if by not in subset.columns:
                raise science.InvalidFilter(f"Unknown column: {by}")
            col = subset[by].dropna()
            if pd.api.types.is_numeric_dtype(col):
                groups = pd.qcut(col, 4, duplicates="drop").value_counts().sort_index()
                counts = {f"{iv.left:.4g} to {iv.right:.4g}": int(n) for iv, n in groups.items()}
            else:
                counts = {str(k): int(v) for k, v in col.value_counts().head(10).items()}
            box["result"] = {"total": len(subset), "by": by, "counts": counts,
                             "missing": int(subset[by].isna().sum())}
            ctx.deps.evidence.append(str(box["result"]))
        except science.InvalidFilter as exc:
            box["result"] = {"error": str(exc)}
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
- Answer every item on the hazard checklist in hazard_responses: point to the population
  filter that handles it, accept the risk and explain it, or mark it not_applicable and
  explain why it doesn't affect this analysis. The method uses planet radius only, so a
  hazard about another column (such as mass) is usually not_applicable. Every filter costs
  planets and statistical power; filter only for hazards that threaten this analysis.
  Unanswered hazards are sent back to you.
Engineering will also always run a sweep of precision cuts and a negative control."""

TACTICAL = """You are Tactical, the adversarial reviewer. Your job is to find reasons NOT to
believe the result. Check for: selection bias from discovery method, circular use of
inferred values, choosing filters after seeing results (p-hacking), low power, measurement
error, and whether the conclusion holds across the whole precision-cut sweep or only at one
setting. To check a result across groups, use breakdown_population once (e.g. by disc_method
or pl_orbper) rather than one count per group. Engineering's interpret_results states, in
code, whether each test is significant and whether the negative control passed; don't
reinterpret those numbers. Critique the analysis's assumptions and choices instead. The negative control must find no valley; if it does, the method is broken.
Accept only if the conclusion survives. Ask for revision if a fixable flaw remains."""

LOG = """You write the Captain's Log: a short public report of the mission for data
scientists. State the finding with its numbers from the results (Silverman p-value, valley
location and its 95% interval, sample size), how the population was chosen, what the
reviewer raised, and the limitations. No hype; never claim more than the evidence supports.
A result that isn't significant is "not significant at this sample size", not "no
evidence", unless the sample was large. Use only numbers from the results. Write in the
first person plural ("we")."""


# Conventions, not results: confidence levels ("95% CI")
CONVENTIONAL = {"90%", "95%", "99%"}
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?%?")


def _values(text):
    out = set()
    for token in _NUMBER.findall(text):
        try:
            out.add(float(token.rstrip("%")))
        except ValueError:
            pass
    return out


def unsupported_numbers(text, evidence):
    """Numbers in `text` (decimals, and integers of 10 or more) that appear nowhere in evidence.

    Matches at the precision the claim is written with, so '0.018' matches 0.0180 and
    '1.72' matches 1.719. Percentages must appear as written or as a fraction.
    """
    known = _values(" ".join(evidence))
    missing = []
    for token in _NUMBER.findall(text):
        if token in CONVENTIONAL:
            continue
        is_pct = token.endswith("%")
        raw = token.rstrip("%")
        value = float(raw)
        if "." not in raw and abs(value) < 10 and not is_pct:
            continue  # small counts and list positions
        places = len(raw.split(".")[1]) if "." in raw else 0
        candidates = {value, value / 100} if is_pct else {value}
        if not any(round(k, places) == round(c, places) or abs(k - c) <= 10 ** -places / 2
                   for k in known for c in candidates):
            missing.append(token)
    return sorted(set(missing))


def check_review_numbers(ctx: RunContext[CrewDeps], review: Review) -> Review:
    """Enforced in code: a review may only cite numbers it was given or counted itself."""
    text = " ".join([review.summary] + [i.detail for i in review.issues])
    missing = unsupported_numbers(text, ctx.deps.evidence)
    if missing:
        ctx.deps.recorder.log(MissionEvent.Station.TACTICAL, MissionEvent.Kind.NOTE,
                              "Review returned: numbers not found in results",
                              rationale="Not in results, data card or counts: " + ", ".join(missing),
                              payload=review.model_dump())
        raise ModelRetry(
            "Your review cites numbers that appear nowhere in the results, the data card, or your "
            f"own count_population calls: {', '.join(missing)}. You cannot compute p-values or "
            "percentages yourself. Cite only numbers you were given or counted, or describe the "
            "concern without a number.")
    return review


def log_problems(log, evidence):
    """What's wrong with a report's numbers. Empty means it cites results and invents nothing."""
    text = " ".join([log.title, log.intro] + log.paragraphs + log.limitations)
    missing = unsupported_numbers(text, evidence)
    cites_results = any("." in t for t in _NUMBER.findall(text)
                        if not unsupported_numbers(t, evidence))
    problems = []
    if missing:
        problems.append("These numbers appear nowhere in the results: " + ", ".join(missing) + ".")
    if not cites_results:
        problems.append("State the result's statistics from the results: the Silverman p-value, "
                        "the valley location and its 95% interval.")
    return problems


def check_log(ctx: RunContext[CrewDeps], log: CaptainsLog) -> CaptainsLog:
    """Enforced in code: the report states result numbers and invents none."""
    problems = log_problems(log, ctx.deps.evidence)
    if problems:
        ctx.deps.recorder.log(MissionEvent.Station.LOG, MissionEvent.Kind.NOTE,
                              "Report returned: statistics missing or not from results",
                              rationale=" ".join(problems), payload=log.model_dump())
        raise ModelRetry("Revise the report. " + " ".join(problems))
    return log


def check_plan_hazards(ctx: RunContext[CrewDeps], plan: AnalysisPlan) -> AnalysisPlan:
    """Enforced in code: a plan that leaves a hazard unanswered goes back to the model."""
    problems = hazard_problems(plan, ctx.deps.hazards)
    if ctx.deps.df is not None and len(ctx.deps.df):
        try:
            science.apply_filters(ctx.deps.df, [f.model_dump(exclude={"reason"}) for f in plan.population])
        except science.InvalidFilter as exc:
            problems.insert(0, f"Population filter problem: {exc}")
    if problems:
        ctx.deps.recorder.log(MissionEvent.Station.SCIENCE, MissionEvent.Kind.NOTE,
                              "Plan returned: hazards not answered or filters invalid",
                              rationale="\n".join(problems), payload=plan.model_dump())
        raise ModelRetry("Revise the plan. " + " ".join(problems))
    return plan


def build_crew(capabilities=()):
    science_officer = _agent("science_officer", AnalysisPlan, SCIENCE,
                             tools=[count_population, breakdown_population, column_summary],
                             capabilities=capabilities,
                             retries=5)
    science_officer.output_validator(check_plan_hazards)
    tactical = _agent("tactical", Review, TACTICAL, tools=[breakdown_population, count_population],
                      capabilities=capabilities, retries=4)
    tactical.output_validator(check_review_numbers)
    captains_log = _agent("captains_log", CaptainsLog, LOG, capabilities=capabilities, retries=4)
    captains_log.output_validator(check_log)
    return {
        "ops": _agent("ops", OpsBrief, OPS, capabilities=capabilities),
        "science": science_officer,
        "tactical": tactical,
        "log": captains_log,
    }


def describe_failure(messages, limit=4000):
    """What the model produced before a failed run, for the mission log."""
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    last = responses[-1] if responses else None
    produced = []
    for part in (last.parts if last else []):
        if isinstance(part, TextPart):
            produced.append(part.content)
        elif isinstance(part, ToolCallPart):
            produced.append(f"{part.tool_name}({part.args_as_json_str()})")
    text = "\n".join(produced)
    return {
        "model_requests": len(responses),
        "tool_calls": [p.tool_name for r in responses for p in r.parts if isinstance(p, ToolCallPart)],
        "last_finish_reason": getattr(last, "finish_reason", None),
        "last_output_chars": len(text),
        "last_output": text[:limit] + ("…[truncated]" if len(text) > limit else ""),
    }


def run_station(agent, station, prompt, deps: CrewDeps):
    """Run one agent within its budget; log its output, or what it produced if it failed."""
    import time

    deps.recorder.current_station = station
    start = time.monotonic()
    with capture_run_messages() as messages:
        try:
            result = agent.run_sync(prompt, deps=deps, usage_limits=STATION_LIMITS.get(station))
        except AgentRunError as exc:
            deps.recorder.log(
                station, MissionEvent.Kind.ERROR, f"{agent.name} failed: {exc}"[:300],
                payload=describe_failure(messages), model_name=MODEL_NAME,
                duration_ms=int((time.monotonic() - start) * 1000))
            raise
    usage = result.usage
    deps.recorder.log(
        station, MissionEvent.Kind.MODEL_OUTPUT, f"{agent.name} output",
        payload=result.output.model_dump(), model_name=MODEL_NAME,
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        duration_ms=int((time.monotonic() - start) * 1000))
    return result.output
