"""Entry point: `python -m nanoswarm "..."`."""
from __future__ import annotations

import argparse
import sys

from .orchestrator import Orchestrator


def main() -> int:
    p = argparse.ArgumentParser(prog="nanoswarm")
    p.add_argument("task", help="Description of the coding task to run.")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--auto-merge", action="store_true",
                   help="Squash-merge passing subtasks into base branch.")
    args = p.parse_args()

    orch = Orchestrator(config_path=args.config)
    report = orch.run(args.task, auto_merge=args.auto_merge)
    n_fail = sum(1 for r in report.results if r.status == "fail")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
