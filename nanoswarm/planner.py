"""Planner: Claude decompõe a tarefa em subtasks com critérios executáveis."""
from __future__ import annotations

import json
from pathlib import Path

from .gateway import Gateway
from .types import Plan, Subtask, Tier

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "planner.md"


class Planner:
    def __init__(self, gateway: Gateway, alias: str = "planner"):
        self.gw = gateway
        self.alias = alias
        self.system = PROMPT_PATH.read_text() if PROMPT_PATH.exists() else _DEFAULT_PROMPT

    def plan(self, task: str, repo_context: str = "") -> Plan:
        user = f"# Repo context\n{repo_context or '(none)'}\n\n# Task\n{task}\n"
        r = self.gw.call(
            self.alias,
            [
                {"role": "system", "content": self.system},
                {"role": "user", "content": user},
            ],
        )
        return _parse_plan(task, r.text)

    def replan(self, subtask: Subtask, failures: list[str]) -> Subtask:
        """Recebe uma subtask que falhou + erros do verifier; retorna versão revisada."""
        user = (
            "The subtask below failed verification. Produce a revised version that addresses "
            "the failures. Reply ONLY with the JSON of a single Subtask.\n\n"
            f"Subtask:\n{subtask.model_dump_json(indent=2)}\n\n"
            f"Failures:\n- " + "\n- ".join(failures)
        )
        r = self.gw.call(
            "planner_light",  # re-plan usa o modelo mais leve
            [
                {"role": "system", "content": "You revise a single Subtask JSON."},
                {"role": "user", "content": user},
            ],
        )
        data = _extract_json(r.text)
        if "id" not in data:
            data["id"] = subtask.id + "_v2"
        return Subtask(**data)


# --------------------------------------------------------------------------- #


def _parse_plan(task: str, raw: str) -> Plan:
    data = _extract_json(raw)
    subs = [Subtask(**s) for s in data.get("subtasks", [])]
    if not subs:
        # fallback: 1 subtask cobrindo tudo
        subs = [Subtask(id="s1", description=task, tier_hint=Tier.STANDARD)]
    return Plan(task=task, rationale=data.get("rationale", ""), subtasks=subs)


def _extract_json(text: str) -> dict:
    """Aceita JSON puro, JSON em fenced code, ou JSON com texto antes/depois."""
    text = text.strip()
    # tentar fence ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try:
                    return json.loads(p)
                except json.JSONDecodeError:
                    continue
    # tentar primeira { até última }
    if "{" in text and "}" in text:
        snippet = text[text.find("{") : text.rfind("}") + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass
    return {}


_DEFAULT_PROMPT = """\
You are the Planner of a multi-model coding agent. Decompose the user's task
into the minimum set of independent subtasks. Each subtask must have:

- `id`: short slug
- `description`: clear, actionable, scoped to the listed files
- `files_to_touch`: explicit list of file paths the worker may modify
- `acceptance`: list of shell commands that MUST exit 0 for the subtask to pass.
  Prefer concrete tests (`pytest tests/foo.py::test_bar`) and static checks
  (`ruff check src/foo.py`, `mypy src/foo.py`). NO vague checklists.
- `tier_hint`: one of "trivial", "standard", "complex".

Return ONLY a JSON object of the form:
{
  "rationale": "...",
  "subtasks": [ { ... }, { ... } ]
}

Be ruthless about minimality. Fewer, sharper subtasks beat many fuzzy ones.
"""
