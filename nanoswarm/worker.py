"""Worker: executa uma subtask isolada num git worktree, via tool-use."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .gateway import Gateway
from .router import Router
from .types import Subtask, Tier

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file inside the worktree.",
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
            "name": "write",
            "description": "Overwrite a file inside the worktree with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": "Run a shell command inside the worktree (timeout 60s).",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that the subtask is complete with a short summary.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]

MAX_STEPS = 12


class Worker:
    def __init__(self, gateway: Gateway, router: Router):
        self.gw = gateway
        self.router = router

    def execute(
        self,
        subtask: Subtask,
        worktree_dir: Path,
        *,
        executor_alias: str | None = None,
    ) -> dict:
        """Roda o loop ReAct até `done` ou MAX_STEPS.

        Se `executor_alias` for passado (vindo do orchestrator), usa-o; senão
        cai pro fallback heurístico (Tier).
        """
        alias = executor_alias or self._fallback_alias(subtask)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"# Subtask\n{subtask.model_dump_json(indent=2)}\n\n"
                    f"# Working directory\n{worktree_dir}\n\n"
                    f"You may only modify files in `files_to_touch`. "
                    f"Call `done` when finished."
                ),
            },
        ]

        for step in range(MAX_STEPS):
            r = self.gw.call(alias, messages, tools=TOOLS)
            tool_calls = r.raw["choices"][0]["message"].get("tool_calls") or []
            if not tool_calls:
                messages.append({"role": "assistant", "content": r.text})
                messages.append({
                    "role": "user",
                    "content": "Use the provided tools. Call `done` when finished.",
                })
                continue

            messages.append(r.raw["choices"][0]["message"])
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                if name == "done":
                    return {
                        "status": "ok", "summary": args.get("summary", ""),
                        "steps": step + 1, "alias": alias,
                    }
                result = self._dispatch(name, args, worktree_dir, subtask)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return {"status": "max_steps", "summary": "exceeded MAX_STEPS",
                "steps": MAX_STEPS, "alias": alias}

    # --- internos ---------------------------------------------------------- #
    def _fallback_alias(self, st: Subtask) -> str:
        tier = st.tier_hint or self.router.classify(st.description, st.files_to_touch)
        if isinstance(tier, str):
            tier = Tier(tier)
        return self.router.alias_for(tier)

    def _dispatch(self, name: str, args: dict, wt: Path, st: Subtask) -> str:
        if name == "read":
            p = wt / args["path"]
            if not p.exists():
                return f"ERROR: {args['path']} not found"
            try:
                return p.read_text()[:20000]
            except Exception as e:  # noqa: BLE001
                return f"ERROR: {e}"

        if name == "write":
            rel = args["path"]
            if st.files_to_touch and rel not in st.files_to_touch:
                return f"ERROR: '{rel}' is not in files_to_touch={st.files_to_touch}"
            p = wt / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"])
            return f"OK: wrote {len(args['content'])} bytes to {rel}"

        if name == "run":
            try:
                out = subprocess.run(
                    args["cmd"], shell=True, cwd=wt,
                    capture_output=True, text=True, timeout=60,
                )
                tail = (out.stdout + out.stderr)[-4000:]
                return f"exit={out.returncode}\n{tail}"
            except subprocess.TimeoutExpired:
                return "ERROR: timeout (60s)"

        return f"ERROR: unknown tool {name}"


_SYSTEM = """\
You are a Worker agent. You execute one subtask inside an isolated git worktree.

Rules:
1. Use the provided tools (read, write, run, done). Do not output free-form code.
2. Only write files listed in `files_to_touch`.
3. Verify your work with the commands in `acceptance` before calling `done`.
4. Be concise. Don't re-read the same file repeatedly.
5. If you can't make progress in a few steps, call `done` with a clear failure summary.
"""
