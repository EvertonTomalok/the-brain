"""Release Scribe: gera PR_BODY.md a partir do plano, resultados e diff."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .gateway import Gateway
from .types import Plan, SubtaskResult


SYSTEM = """\
You write concise PR descriptions. Markdown. Be factual. No flourish.

Sections (use these exact headings):
## What
1-3 sentences.
## Why
1-2 sentences.
## Files touched
bullet list.
## Commands run
bullet list with exit codes if known.
## Residual risks
bullet list (or "none identified").

If guardrail categories were triggered, add:
## ⚠️ Sensitive areas
listing each category and why human review is required before merge.
"""


class ReleaseScribe:
    def __init__(self, gateway: Gateway, alias: str = "scribe"):
        self.gw = gateway
        self.alias = alias

    def write(
        self,
        plan: Plan,
        results: list[SubtaskResult],
        worktree: Path | None = None,
        guardrail_categories: list[str] | None = None,
    ) -> str:
        files_touched = sorted({f for sr in results for f in sr.subtask.files_to_touch})
        cmds = sorted({c for sr in results for c in sr.subtask.acceptance})
        statuses = "\n".join(f"- {sr.subtask.id}: {sr.status}" for sr in results)
        diff_excerpt = self._diff(worktree)[:6000] if worktree else ""

        user = (
            f"# Original task\n{plan.task}\n\n"
            f"# Plan rationale\n{plan.rationale or '(none)'}\n\n"
            f"# Subtasks status\n{statuses}\n\n"
            f"# Files touched\n{', '.join(files_touched) or '(none)'}\n\n"
            f"# Acceptance commands run\n" + "\n".join(f"- {c}" for c in cmds) + "\n\n"
            f"# Guardrail categories triggered\n{', '.join(guardrail_categories or []) or '(none)'}\n\n"
            f"# Diff excerpt\n```diff\n{diff_excerpt}\n```\n"
        )
        try:
            r = self.gw.call(
                self.alias,
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                ],
            )
            return r.text
        except Exception as e:  # noqa: BLE001
            return f"# PR\n\n_(scribe failed: {e})_\n\n## Files\n" + ", ".join(files_touched)

    @staticmethod
    def _diff(wt: Path) -> str:
        r = subprocess.run(
            ["git", "diff", "HEAD"], cwd=wt, capture_output=True, text=True
        )
        return r.stdout
