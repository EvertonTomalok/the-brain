"""Memory em arquivos planos. Sem vector DB."""
from __future__ import annotations

import time
from pathlib import Path


class Memory:
    def __init__(self, base_dir: str | Path = ".swarm/memory"):
        self.dir = Path(base_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.facts = self.dir / "facts.md"
        self.decisions = self.dir / "decisions.md"
        self.scratch = self.dir / "scratchpad.md"
        for p in [self.facts, self.decisions, self.scratch]:
            p.touch(exist_ok=True)

    def add_fact(self, fact: str) -> None:
        with self.facts.open("a") as f:
            f.write(f"- {fact}\n")

    def add_decision(self, what: str, why: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.decisions.open("a") as f:
            f.write(f"\n## {ts}\n**What:** {what}\n**Why:** {why}\n")

    def repo_context(self, max_chars: int = 4000) -> str:
        """Devolve facts + últimas decisões — pra alimentar o planner."""
        out = ["# Facts", self.facts.read_text(), "", "# Recent decisions"]
        decisions = self.decisions.read_text().splitlines()[-80:]
        out.append("\n".join(decisions))
        return "\n".join(out)[:max_chars]

    def reset_scratch(self) -> None:
        self.scratch.write_text("")
