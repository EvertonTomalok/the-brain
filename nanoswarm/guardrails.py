"""Guardrails: padrões que forçam escalação automática para frontier + 2-reviewer.

Disparados se a descrição da tarefa, files_to_touch, ou o diff resultante
baterem qualquer padrão. Efeitos: risk=high, executor=high, review=2-vendor,
auto_merge bloqueado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GUARDRAIL_PATTERNS: dict[str, list[str]] = {
    "auth":        [r"\bauth\b", r"login", r"oauth", r"\bjwt\b", r"session[^_]"],
    "payments":    [r"stripe", r"paypal", r"billing", r"invoice", r"\bpayment"],
    "crypto":      [r"encrypt", r"decrypt", r"\bhash\b", r"crypto", r"key[ _-]?management"],
    "multitenant": [r"\btenant", r"workspace_id", r"\borg_id"],
    "secrets":     [r"\.env", r"secret", r"api[ _-]?key", r"\btoken\b"],
    "migration":   [r"migration", r"alembic", r"schema_change"],
    "infra":       [r"terraform", r"kubernetes", r"docker[ -]?compose"],
    "concurrency": [r"asyncio", r"threading", r"\block\b", r"mutex", r"\brace\b"],
    "deletion":    [r"DELETE FROM", r"drop_table", r"\bunlink\b", r"rm -rf"],
    "compliance":  [r"\bgdpr\b", r"\bpii\b", r"\bhipaa\b", r"\blicense\b"],
}


@dataclass
class GuardrailHit:
    category: str
    pattern: str
    where: str   # "task" | "file" | "diff"
    snippet: str = ""


def _scan(text: str, where: str) -> list[GuardrailHit]:
    hits: list[GuardrailHit] = []
    for category, patterns in GUARDRAIL_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                hits.append(GuardrailHit(
                    category=category, pattern=pat, where=where, snippet=m.group(0)
                ))
    return hits


def scan_task(task: str, files: list[str] | None = None) -> list[GuardrailHit]:
    hits = _scan(task, "task")
    for f in files or []:
        hits += _scan(f, "file")
    return _dedup(hits)


def scan_diff(diff: str) -> list[GuardrailHit]:
    return _dedup(_scan(diff, "diff"))


def _dedup(hits: list[GuardrailHit]) -> list[GuardrailHit]:
    seen: set[tuple[str, str, str]] = set()
    out: list[GuardrailHit] = []
    for h in hits:
        k = (h.category, h.where, h.snippet.lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def categories(hits: list[GuardrailHit]) -> set[str]:
    return {h.category for h in hits}
