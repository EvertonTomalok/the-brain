"""Triage agent: classifica task em (task_type, risk, files prováveis).

Roda primeiro, antes de scout/planner. Usa modelo barato e devolve JSON.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .gateway import Gateway
from .planner import _extract_json

TASK_TYPES = [
    "docs", "tests", "frontend", "backend_feature", "refactor", "bug",
    "performance", "auth_security_payments", "data_migration",
]
RISKS = ["low", "medium", "high"]


class Triage(BaseModel):
    task_type: str = "backend_feature"
    risk: str = "medium"
    expected_files: list[str] = Field(default_factory=list)
    validation_hints: list[str] = Field(default_factory=list)
    reasoning: str = ""


SYSTEM = f"""\
You classify coding tasks into a routing JSON. Be terse.

Reply ONLY with a JSON object:
{{
  "task_type": one of {TASK_TYPES},
  "risk": one of {RISKS},
  "expected_files": ["path/glob/...", ...],
  "validation_hints": ["pytest tests/x", "npm run lint"],
  "reasoning": "1 line"
}}

Risk rubric:
- low: docs, comments, formatting, single typo.
- medium: implement function, fix bug in 1-2 files, write tests.
- high: anything touching auth, payments, crypto, multi-tenant, secrets,
        data migration, infra, concurrency, deletion, compliance, or
        cross-cutting refactors of >5 files.
"""


class TriageAgent:
    def __init__(self, gateway: Gateway, alias: str = "triage"):
        self.gw = gateway
        self.alias = alias

    def run(self, task: str) -> Triage:
        try:
            r = self.gw.call(
                self.alias,
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Task: {task}"},
                ],
            )
            data = _extract_json(r.text)
            t = Triage(**{k: v for k, v in data.items() if k in Triage.model_fields})
            if t.task_type not in TASK_TYPES:
                t.task_type = "backend_feature"
            if t.risk not in RISKS:
                t.risk = "medium"
            return t
        except Exception:
            return Triage(reasoning="triage fallback (default)")
