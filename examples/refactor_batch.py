"""Exemplo: refactor automatizado em larga escala.

Tipicamente: extrair um módulo e atualizar todos os call-sites.
"""
from __future__ import annotations

import sys

from nanoswarm.orchestrator import Orchestrator

TASK = """\
Refactor: extract `UserService` from `src/legacy/users.py` into a new module
`src/services/user_service.py`. Update all import sites under `src/` and
`tests/` to use the new path. Keep the public API identical.
"""


def main() -> int:
    orch = Orchestrator()
    report = orch.run(TASK, auto_merge=False)  # revisar antes de mergear
    return 0 if all(r.status == "ok" for r in report.results) else 1


if __name__ == "__main__":
    sys.exit(main())
