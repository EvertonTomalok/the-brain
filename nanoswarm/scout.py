"""Context Scout: read-only mapper. Roda antes do planner.

Modelo barato (Kimi K2.6 ou GLM-5). Tools: read, grep, ls. Nunca edita.
Devolve resumo curto: símbolos relevantes, callers, padrões, riscos.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .gateway import Gateway

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List files in a directory (relative to repo root).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Ripgrep across the repo. Returns at most 50 matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "glob": {"type": "string", "description": "optional glob filter"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file. Use sparingly — prefer grep + ranges.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summary",
            "description": "Submit the final JSON summary and stop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relevant_files": {"type": "array", "items": {"type": "string"}},
                    "key_symbols": {"type": "array", "items": {"type": "string"}},
                    "patterns": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["relevant_files"],
            },
        },
    },
]

MAX_STEPS = 10


class ScoutResult(BaseModel):
    relevant_files: list[str] = Field(default_factory=list)
    key_symbols: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    raw_steps: int = 0

    def as_context(self) -> str:
        parts = ["## Scout findings"]
        if self.relevant_files:
            parts.append("**Relevant files:** " + ", ".join(self.relevant_files[:20]))
        if self.key_symbols:
            parts.append("**Key symbols:** " + ", ".join(self.key_symbols[:20]))
        if self.patterns:
            parts.append("**Patterns:**\n- " + "\n- ".join(self.patterns[:10]))
        if self.risks:
            parts.append("**Risks:**\n- " + "\n- ".join(self.risks[:10]))
        return "\n\n".join(parts)


SYSTEM = """\
You are the Context Scout. You are READ-ONLY. You map the repository to brief
the planner. Never write, never run, never edit.

Use grep extensively, read files only when grep is insufficient. Submit a
short summary via the `summary` tool when you have enough information.

Be concise. The planner only needs:
- which files matter
- which symbols/functions are relevant
- existing patterns (test style, error handling, naming)
- risks (auth, payments, crypto, concurrency, data, etc.)
"""


class Scout:
    def __init__(self, gateway: Gateway, alias: str = "scout", repo: Path = Path(".")):
        self.gw = gateway
        self.alias = alias
        self.repo = repo

    def explore(self, task: str) -> ScoutResult:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"# Task\n{task}"},
        ]
        for step in range(MAX_STEPS):
            r = self.gw.call(self.alias, messages, tools=TOOLS)
            tool_calls = r.raw["choices"][0]["message"].get("tool_calls") or []
            if not tool_calls:
                messages.append({"role": "assistant", "content": r.text})
                messages.append({"role": "user", "content": "Use the tools. Submit `summary` when done."})
                continue
            messages.append(r.raw["choices"][0]["message"])
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                if name == "summary":
                    return ScoutResult(raw_steps=step + 1, **args)
                result = self._dispatch(name, args)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        return ScoutResult(raw_steps=MAX_STEPS, risks=["scout exceeded MAX_STEPS"])

    # --- read-only tools --------------------------------------------------- #
    def _dispatch(self, name: str, args: dict) -> str:
        if name == "ls":
            p = self.repo / args.get("path", ".")
            if not p.exists():
                return f"ERROR: {p} not found"
            entries = sorted(x.name for x in p.iterdir())
            return "\n".join(entries[:200])

        if name == "grep":
            cmd = ["rg", "-n", "--max-count", "50", args["pattern"]]
            if args.get("glob"):
                cmd += ["-g", args["glob"]]
            try:
                r = subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, timeout=30)
                out = (r.stdout or r.stderr)[:6000]
                return out or "(no matches)"
            except FileNotFoundError:
                return "ERROR: ripgrep (rg) not installed"
            except subprocess.TimeoutExpired:
                return "ERROR: timeout"

        if name == "read":
            p = self.repo / args["path"]
            if not p.exists():
                return f"ERROR: {args['path']} not found"
            try:
                return p.read_text()[:8000]
            except Exception as e:  # noqa: BLE001
                return f"ERROR: {e}"

        return f"ERROR: unknown tool {name}"
