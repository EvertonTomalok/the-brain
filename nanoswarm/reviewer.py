"""Cross-vendor reviewer. SEMPRE roda em fornecedor diferente do executor.

Diferente do `verifier` (que faz fast-path com Haiku sobre diff). Este é o
review estruturado, executado depois que o verifier passa, antes do merge.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .gateway import Gateway
from .planner import _extract_json
from .types import Subtask

Verdict = Literal["approve", "request_changes", "reject"]


class Finding(BaseModel):
    severity: Literal["info", "warning", "critical"] = "warning"
    file: str = ""
    line: int | None = None
    message: str


class Review(BaseModel):
    verdict: Verdict
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    reviewer_alias: str = ""
    cost_usd: float = 0.0


SYSTEM = """\
You are an independent code reviewer. You did not write this code and you do
not assume the author's intent. Review the diff as if shipping to production.

Look for:
- functional correctness
- regressions and edge cases
- security (injection, secrets, auth bypasses)
- performance (obvious O(n²) where O(n) suffices)
- coupling and unnecessary scope creep
- tests that only assert on mocks
- accidental deletions

Reply with EXACTLY this JSON:
{
  "verdict": "approve" | "request_changes" | "reject",
  "summary": "1-3 sentences",
  "findings": [
    {"severity": "info|warning|critical", "file": "path", "line": 42, "message": "..."}
  ]
}

`approve` only if you'd merge it as-is. `request_changes` for fixable issues.
`reject` for fundamental problems (broken design, security holes, data loss risk).
"""


class Reviewer:
    def __init__(self, gateway: Gateway):
        self.gw = gateway
        self.review_pairs = gateway.cfg.get("review_pairs", {})

    def review(
        self,
        subtask: Subtask,
        worktree: Path,
        executor_alias: str,
        *,
        require_two: bool = False,
    ) -> list[Review]:
        """Roda 1 ou 2 reviewers cross-vendor. Devolve lista (1 ou 2 reviews)."""
        diff = self._diff(worktree)
        if not diff.strip():
            return [Review(verdict="approve", summary="empty diff", reviewer_alias="(none)")]

        executor_vendor = self._vendor_of(executor_alias)
        primary_alias = self.review_pairs.get(executor_vendor, "reviewer_anthropic")
        reviews = [self._one_review(subtask, diff, primary_alias)]

        if require_two:
            # segundo reviewer: tenta um vendor diferente do primário
            secondary = self._pick_secondary(primary_alias)
            if secondary:
                reviews.append(self._one_review(subtask, diff, secondary))
        return reviews

    @staticmethod
    def aggregate(reviews: list[Review]) -> Verdict:
        verdicts = [r.verdict for r in reviews]
        if "reject" in verdicts:
            return "reject"
        if "request_changes" in verdicts:
            return "request_changes"
        return "approve"

    # --- internos ---------------------------------------------------------- #
    def _vendor_of(self, alias: str) -> str:
        spec = self.gw.models.get(alias, {})
        model = spec.get("model", "")
        if model.startswith("anthropic/"):
            return "anthropic"
        if model.startswith("openai/"):
            return "openai"
        if model.startswith("deepseek/"):
            return "deepseek"
        if "moonshot" in model:
            return "moonshot"
        if "zai" in model or "z.ai" in model or "glm" in model:
            return "zai-org"
        return "unknown"

    def _pick_secondary(self, primary_alias: str) -> str | None:
        primary_vendor = self._vendor_of(primary_alias)
        candidates = ["reviewer_anthropic", "reviewer_openai", "reviewer_deepseek"]
        for c in candidates:
            if c != primary_alias and self._vendor_of(c) != primary_vendor:
                if c in self.gw.models:
                    return c
        return None

    def _one_review(self, st: Subtask, diff: str, alias: str) -> Review:
        prompt = (
            f"# Subtask\n{st.description}\n\n"
            f"# Files in scope\n{', '.join(st.files_to_touch) or '(any)'}\n\n"
            f"# Diff\n```diff\n{diff[:25000]}\n```"
        )
        try:
            r = self.gw.call(
                alias,
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            data = _extract_json(r.text)
            review = Review(
                verdict=data.get("verdict", "request_changes"),
                summary=data.get("summary", ""),
                findings=[Finding(**f) for f in data.get("findings", [])],
                reviewer_alias=alias,
                cost_usd=r.cost_usd,
            )
            if review.verdict not in ("approve", "request_changes", "reject"):
                review.verdict = "request_changes"
            return review
        except Exception as e:  # noqa: BLE001
            return Review(
                verdict="request_changes",
                summary=f"reviewer error: {e}",
                reviewer_alias=alias,
            )

    @staticmethod
    def _diff(cwd: Path) -> str:
        r = subprocess.run(
            ["git", "diff", "HEAD"], cwd=cwd, capture_output=True, text=True
        )
        return r.stdout
