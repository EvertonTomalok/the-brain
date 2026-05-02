"""Exemplo: codegen massivo. 1 spec JSON -> 1 componente.

Uso:
    python examples/codegen_components.py specs/*.json
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from nanoswarm.orchestrator import Orchestrator


def main(globs: list[str]) -> int:
    files = [f for g in globs for f in glob.glob(g)]
    if not files:
        print("no spec files matched", file=sys.stderr)
        return 1

    orch = Orchestrator()
    failures = 0
    for spec_path in files:
        spec = json.loads(Path(spec_path).read_text())
        task = (
            f"Generate a React component named `{spec['name']}` based on this spec, "
            f"with a snapshot test. Spec:\n{json.dumps(spec, indent=2)}\n"
            f"Write to src/components/{spec['name']}.tsx and "
            f"tests/components/{spec['name']}.test.tsx."
        )
        report = orch.run(task)
        if any(r.status == "fail" for r in report.results):
            failures += 1
    print(f"\n{len(files) - failures}/{len(files)} components generated.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
