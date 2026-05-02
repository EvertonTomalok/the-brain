"""Tipos compartilhados. Pequeno e estável."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Tier(str, Enum):
    TRIVIAL = "trivial"
    STANDARD = "standard"
    COMPLEX = "complex"


class Subtask(BaseModel):
    """Uma unidade de trabalho que um worker isolado pode executar."""

    id: str
    description: str
    files_to_touch: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(
        default_factory=list,
        description="Comandos shell que precisam terminar com exit 0 para a subtask passar.",
    )
    tier_hint: Optional[Tier] = None


class Plan(BaseModel):
    task: str
    rationale: str = ""
    subtasks: list[Subtask]


class Verdict(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)
    notes: str = ""
    critic_verdict: Optional[Literal["pass", "fail", "warn"]] = None


class SubtaskResult(BaseModel):
    subtask: Subtask
    status: Literal["ok", "fail", "skipped"]
    verdict: Optional[Verdict] = None
    cost_usd: float = 0.0


class Report(BaseModel):
    task: str
    results: list[SubtaskResult]
    total_cost_usd: float
    wall_time_s: float
