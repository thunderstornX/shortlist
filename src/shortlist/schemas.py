"""Data contracts. Every boundary in the system speaks one of these."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Importance(str, Enum):
    ESSENTIAL = "essential"
    DESIRABLE = "desirable"


class Criterion(BaseModel):
    """One requirement lifted out of a job posting."""

    id: str = Field(description="Stable short id, e.g. C1")
    text: str = Field(min_length=3, description="The requirement in the employer's words")
    importance: Importance

    @field_validator("text")
    @classmethod
    def _single_requirement(cls, v: str) -> str:
        # A criterion bundling several requirements cannot be scored cleanly,
        # which is the most common way criteria-based screening goes wrong.
        if v.count(";") > 1:
            raise ValueError("criterion looks like several requirements; split it")
        return v.strip()


class JobSpec(BaseModel):
    source: str = Field(description="URL or file path the posting came from")
    title: str
    organisation: str | None = None
    criteria: list[Criterion]

    @field_validator("criteria")
    @classmethod
    def _has_essential(cls, v: list[Criterion]) -> list[Criterion]:
        if not any(c.importance == Importance.ESSENTIAL for c in v):
            raise ValueError("no essential criteria found; a spec with none cannot rank")
        return v

    def essential(self) -> list[Criterion]:
        return [c for c in self.criteria if c.importance == Importance.ESSENTIAL]


Verdict = Literal["met", "partial", "not_met", "unsupported"]


class Assessment(BaseModel):
    """One candidate judged against one criterion."""

    criterion_id: str
    verdict: Verdict
    # Must be a verbatim span of the CV for met/partial. Enforced in grounding.py,
    # not trusted from the model.
    quote: str = ""
    reasoning: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = False
    needs_human: bool = False

    @field_validator("quote")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()


class CandidateReport(BaseModel):
    candidate_id: str
    source_file: str
    assessments: list[Assessment]
    essential_met: int = 0
    essential_total: int = 0
    desirable_met: int = 0
    desirable_total: int = 0
    grounding_rate: float = 0.0
    flags: list[str] = Field(default_factory=list)
    next_action: str = ""

    def score(self) -> float:
        """Essential criteria dominate; desirables break ties. Never a single opaque number."""
        if self.essential_total == 0:
            return 0.0
        ess = self.essential_met / self.essential_total
        des = (self.desirable_met / self.desirable_total) if self.desirable_total else 0.0
        return round(ess + 0.1 * des, 4)
