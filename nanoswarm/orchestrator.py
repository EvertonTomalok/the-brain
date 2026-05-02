"""Pipeline completo: Triage → Scout → Planner → Worker → Verifier → Reviewer → Scribe.

Cada papel é opcional via flags do constructor; o default roda tudo.
"""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import guardrails as gr
from . import worktree as wt_mod
from .gateway import Gateway
from .memory import Memory
from .planner import Planner
from .release_scribe import ReleaseScribe
from .reviewer import Reviewer
from .router import Router
from .scout import Scout, ScoutResult
from .triage import Triage, TriageAgent
from .types import Plan, Report, Subtask, SubtaskResult
from .verifier import Verifier
from .worker import Worker

console = Console()


class Orchestrator:
    def __init__(
        self,
        config_path: str = "config.yaml",
        repo: Path = Path("."),
        *,
        use_triage: bool = True,
        use_scout: bool = True,
        use_reviewer: bool = True,
        use_scribe: bool = True,
    ):
        self.gw = Gateway(config_path)
        self.router = Router(self.gw)
        self.planner = Planner(self.gw)
        self.worker = Worker(self.gw, self.router)
        self.verifier = Verifier(self.gw)
        self.reviewer = Reviewer(self.gw)
        self.scout = Scout(self.gw, repo=repo)
        self.triage = TriageAgent(self.gw)
        self.scribe = ReleaseScribe(self.gw)
        self.memory = Memory(self.gw.cfg.get("memory", {}).get("dir", ".swarm/memory"))
        self.repo = repo
        wt_cfg = self.gw.cfg.get("worktree", {})
        self.wt_base = wt_cfg.get("base_dir", ".swarm/wt")
        self.wt_prefix = wt_cfg.get("branch_prefix", "swarm/")
        self.use_triage = use_triage
        self.use_scout = use_scout
        self.use_reviewer = use_reviewer
        self.use_scribe = use_scribe
        self.defaults = self.gw.cfg.get("defaults", {})

    # ── pipeline principal ─────────────────────────────────────────────── #
    def run(self, task: str, *, auto_merge: bool = False) -> Report:
        t0 = time.time()
        console.rule(f"[bold]nanoswarm[/] · {task[:80]}")

        # 1. Triage
        triage_result = self.triage.run(task) if self.use_triage else Triage()
        self._print_triage(triage_result)

        # 2. Guardrails (na entrada)
        gr_hits = gr.scan_task(task, triage_result.expected_files)
        if gr_hits:
            console.print(f"[yellow]⚠ guardrails: {sorted(gr.categories(gr_hits))}[/]")
            triage_result.risk = "high"

        # 3. Scout (se a política pedir plano)
        policy = self.router.policy_for(triage_result.task_type)
        scout_ctx = ""
        if self.use_scout and policy.get("plan", True):
            scout_result: ScoutResult = self.scout.explore(task)
            scout_ctx = scout_result.as_context()

        # 4. Planner
        repo_ctx = self.memory.repo_context()
        full_ctx = f"{repo_ctx}\n\n{scout_ctx}".strip()
        plan: Plan = self.planner.plan(task, repo_context=full_ctx)
        self._print_plan(plan)

        # 5. Workers em worktrees isolados
        executor_alias = self.router.choose_executor(
            triage_result.task_type, triage_result.risk,
            guardrail_categories=gr.categories(gr_hits),
        )
        results: list[SubtaskResult] = []
        for st in plan.subtasks:
            results.append(self._run_subtask(st, executor_alias, auto_merge=auto_merge,
                                             gr_categories=gr.categories(gr_hits)))

        # 6. Release Scribe
        if self.use_scribe and any(sr.status == "ok" for sr in results):
            pr_body = self.scribe.write(
                plan, results, worktree=None,
                guardrail_categories=sorted(gr.categories(gr_hits)),
            )
            (Path(".swarm") / f"PR_BODY_{int(t0)}.md").parent.mkdir(parents=True, exist_ok=True)
            Path(f".swarm/PR_BODY_{int(t0)}.md").write_text(pr_body)
            console.print("[dim]PR_BODY written to .swarm/PR_BODY_*.md[/]")

        total_cost = self._total_cost_since(t0)
        report = Report(
            task=task, results=results,
            total_cost_usd=total_cost, wall_time_s=time.time() - t0,
        )
        self._print_report(report)
        return report

    # ── execução de uma subtask ────────────────────────────────────────── #
    def _run_subtask(
        self,
        st: Subtask,
        executor_alias: str,
        *,
        auto_merge: bool,
        gr_categories: set[str],
    ) -> SubtaskResult:
        with wt_mod.scoped(
            st.id, repo=self.repo, base_dir=self.wt_base, branch_prefix=self.wt_prefix
        ) as wt:
            console.print(f"[cyan]» {st.id}[/] {st.description[:80]}  [dim]({executor_alias})[/]")

            self.worker.execute(st, wt, executor_alias=executor_alias)
            verdict = self.verifier.verify(st, wt)

            if not verdict.passed:
                # 1 retry com planner_light + executor barato
                attempts = self.defaults.get("max_cheap_attempts", 2)
                for i in range(attempts - 1):
                    console.print(f"[yellow]  re-planning attempt {i + 2}…[/]")
                    st = self.planner.replan(st, verdict.failures)
                    self.worker.execute(st, wt, executor_alias=executor_alias)
                    verdict = self.verifier.verify(st, wt)
                    if verdict.passed:
                        break
                if not verdict.passed:
                    return SubtaskResult(subtask=st, status="fail", verdict=verdict)

            # Diff guardrails (após executar)
            diff_hits = gr.scan_diff(self._diff(wt))
            all_categories = gr_categories | gr.categories(diff_hits)

            # Cross-vendor reviewer
            review_required = self.router.review_required(
                "backend_feature", guardrail_categories=all_categories
            )
            require_two = review_required == "required_two_models"
            block_merge = bool(all_categories) and self.defaults.get(
                "block_auto_merge_on_guardrail", True
            )

            if self.use_reviewer and review_required != "optional":
                reviews = self.reviewer.review(
                    st, wt, executor_alias=executor_alias, require_two=require_two,
                )
                final = Reviewer.aggregate(reviews)
                console.print(f"[magenta]  reviewer ({len(reviews)}x): {final}[/]")
                if final == "reject":
                    verdict.notes += " | reviewer: REJECT"
                    return SubtaskResult(subtask=st, status="fail", verdict=verdict)
                if final == "request_changes":
                    verdict.notes += " | reviewer: changes requested (manual)"

            wt_mod.commit_all(wt, f"swarm: {st.id} — {st.description[:60]}")
            if auto_merge and not block_merge:
                wt_mod.merge_into_base(wt, repo=self.repo)
            elif auto_merge and block_merge:
                console.print("[yellow]  auto_merge blocked by guardrails — manual review required[/]")
            return SubtaskResult(subtask=st, status="ok", verdict=verdict)

    # ── helpers ────────────────────────────────────────────────────────── #
    @staticmethod
    def _diff(wt: Path) -> str:
        import subprocess
        r = subprocess.run(["git", "diff", "HEAD"], cwd=wt, capture_output=True, text=True)
        return r.stdout

    def _total_cost_since(self, t0: float) -> float:
        import json as _json
        total = 0.0
        if not self.gw.spend_log.exists():
            return 0.0
        for line in self.gw.spend_log.read_text().splitlines():
            try:
                rec = _json.loads(line)
                if rec.get("ts", 0) >= t0:
                    total += rec.get("cost_usd", 0.0)
            except Exception:
                continue
        return total

    def _print_triage(self, t: Triage) -> None:
        console.print(
            f"[blue]triage[/] type=[bold]{t.task_type}[/] risk=[bold]{t.risk}[/] "
            f"files={t.expected_files[:3]}{'…' if len(t.expected_files) > 3 else ''}"
        )

    def _print_plan(self, plan: Plan) -> None:
        t = Table(title="Plan", show_lines=False)
        t.add_column("id"); t.add_column("description"); t.add_column("files"); t.add_column("tier")
        for s in plan.subtasks:
            t.add_row(s.id, s.description[:60], ", ".join(s.files_to_touch[:3]),
                      s.tier_hint.value if s.tier_hint else "-")
        console.print(t)

    def _print_report(self, r: Report) -> None:
        t = Table(title=f"Report — ${r.total_cost_usd:.4f} · {r.wall_time_s:.1f}s")
        t.add_column("id"); t.add_column("status"); t.add_column("critic"); t.add_column("notes")
        for sr in r.results:
            crit = sr.verdict.critic_verdict if sr.verdict else "-"
            note = (sr.verdict.notes if sr.verdict else "")[:50]
            t.add_row(sr.subtask.id, sr.status, crit or "-", note)
        console.print(t)
