"""Typed outputs for each station. The model must fill these; code validates them."""
from typing import Literal

from pydantic import BaseModel, Field

FilterColumn = Literal[
    "disc_method", "disc_year", "pl_orbper", "pl_rade", "rade_rel_err", "pl_bmassprov",
    "pl_eqt", "pl_insol", "st_teff", "st_rad", "st_mass", "sy_dist", "sy_pnum",
]
FilterOp = Literal["eq", "ne", "lt", "le", "gt", "ge", "notna"]


class Hazard(BaseModel):
    name: str = Field(description="Short name, e.g. 'inferred masses'")
    evidence: str = Field(description="The number from the data card that shows it")
    implication: str = Field(description="What an analysis must do about it")


class OpsBrief(BaseModel):
    summary: str = Field(description="Two or three sentences on what the data is")
    hazards: list[Hazard] = Field(min_length=1)


class PopulationFilter(BaseModel):
    column: FilterColumn
    op: FilterOp
    value: float | str | None = None
    reason: str


class Alternative(BaseModel):
    option: str
    why_not: str


class HazardResponse(BaseModel):
    hazard_id: str = Field(description="The hazard's ID from the checklist, e.g. 'H1'")
    response: Literal["filter", "accept_risk", "not_applicable"] = Field(
        description="'filter': a population filter handles it. 'accept_risk': it affects this "
                    "analysis but can't be fully handled; explain the risk. 'not_applicable': it "
                    "doesn't affect this analysis (e.g. it concerns a column the method doesn't "
                    "use); explain why")
    filter_number: int | None = Field(
        default=None, description="For 'filter': which population filter handles it (1 = first)")
    explanation: str = Field(description="How this response deals with the hazard")


class AnalysisPlan(BaseModel):
    hypothesis: str
    null_hypothesis: str
    population: list[PopulationFilter] = Field(
        min_length=1, description="Filters applied in order to choose which planets to study")
    bandwidth_dex: float = Field(ge=0.02, le=0.08,
                                 description="Kernel bandwidth in log10(radius), e.g. 0.04")
    significance_level: float = Field(ge=0.001, le=0.1)
    falsification: str = Field(description="The result that would make you reject the hypothesis")
    alternatives_considered: list[Alternative] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    hazard_responses: list[HazardResponse] = Field(
        min_length=1, description="Exactly one response for every hazard on the checklist")


class Issue(BaseModel):
    category: Literal["selection_bias", "circularity", "p_hacking", "power",
                      "measurement_error", "robustness", "other"]
    severity: Literal["low", "medium", "high"]
    detail: str


class Review(BaseModel):
    verdict: Literal["accept", "revise", "reject"]
    issues: list[Issue]
    confidence: Literal["low", "moderate", "high"]
    summary: str


class CaptainsLog(BaseModel):
    title: str = Field(max_length=120)
    intro: str = Field(max_length=250, description="One-sentence summary of the finding")
    paragraphs: list[str] = Field(min_length=2, max_length=6)
    limitations: list[str] = Field(min_length=1)
