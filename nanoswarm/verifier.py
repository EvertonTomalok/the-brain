"""Verifier: roda os comandos de aceite + critic LLM (Haiku) sobre o diff."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .gateway import Gateway
from .types import Subtask, Verdict


class Verifier:
    def __init__(self, gateway: Gateway):
        self.gw = gateway
        self.cfg = gateway.cfg.get("verifier", {})

    def verify(self, subtask: Subtask, worktree_dir: Path) -> Verdict:
        failures: list[str] = []

        # 1) determinístico: rodar `acceptance` + `always_run`
        cmds = list(subtask.acceptance) + self._always_run_for(subtask)
        for cmd in cmds:
            ok, output = self._run(cmd, worktree_dir)
            if not ok:
                failures.append(f"$ {cmd}\n{output[-1500:]}")

        # 2) probabilístico: critic Haiku sobre o diff
        diff = self._diff(worktree_dir)
        critic = self._critic(subtask, diff) if diff else None

        passed = (not failures) and (
            critic is None or critic != "fail" or not self.cfg.get("block_on_critic_fail", False)
        )
        return Verdict(
            passed=passed,
            failures=failures,
            critic_verdict=critic,
            notes=("critic blocked" if (critic == "fail" and not passed) else ""),
        )

    # --- internos ---------------------------------------------------------- #
    def _always_run_for(self, st: Subtask) -> list[str]:
        tmpls = self.cfg.get("always_run", [])
        files = " ".join(st.files_to_touch) if st.files_to_touch else "."
        return [t.replace("{files}", files) for t in tmpls]

    @staticmethod
    def _run(cmd: str, cwd: Path) -> tuple[bool, str]:
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120
            )
            return r.returncode == 0, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"

    @staticmethod
    def _diff(cwd: Path) -> str:
        r = subprocess.run(
            ["git", "diff", "HEAD"], cwd=cwd, capture_output=True, text=True
        )
        return r.stdout[:30000]

    def _critic(self, st: Subtask, diff: str) -> str | None:
        strictness = self.cfg.get("critic_strictness", "normal")
        prompt = (
            f"You are a strict code reviewer ({strictness}). Verdict in one word: "
            f"`pass`, `warn`, or `fail`. Look for: hardcoded secrets, broken logic, "
            f"tests that only check mocks, accidental deletions.\n\n"
            f"Subtask: {st.description}\n\n"
            f"Diff:\n```\n{diff}\n```\n\n"
            f"Reply: <verdict>\n<one-line justification>"
        )
        try:
            r = self.gw.call("critic", [{"role": "user", "content": prompt}])
            first = r.text.strip().split()[0].lower().strip(".:`")
            if first in {"pass", "warn", "fail"}:
                return first
        except Exception:
            pass
        return None
