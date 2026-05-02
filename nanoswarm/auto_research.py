"""Auto-research loop estilo Karpathy: varia config e mede contra eval suite.

Inspirado em github.com/karpathy/autoresearch — deixa rodando à noite, ele
descobre Pareto-ótimos em (custo, qualidade, latência) sozinho.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from copy import deepcopy
from pathlib import Path

import yaml
from rich.console import Console

from .orchestrator import Orchestrator

console = Console()

# Espaço de busca. Adicione/remova conforme o que importa pra você.
SEARCH_SPACE = {
    "router.complex_threshold_files": [2, 3, 4, 5],
    "router.tier_to_alias.standard": ["worker_std", "worker_fast", "worker_swarm"],
    "router.tier_to_alias.complex": ["worker_heavy", "worker_std"],
    "verifier.critic_strictness": ["lenient", "normal", "strict"],
}


def _set(d: dict, dotted: str, value):
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur[k]
    cur[keys[-1]] = value


def sample_cfg(base: dict) -> dict:
    cfg = deepcopy(base)
    chosen = {}
    for k, opts in SEARCH_SPACE.items():
        v = random.choice(opts)
        _set(cfg, k, v)
        chosen[k] = v
    return cfg, chosen


def grid_iter(base: dict):
    keys = list(SEARCH_SPACE.keys())
    for combo in itertools.product(*[SEARCH_SPACE[k] for k in keys]):
        cfg = deepcopy(base)
        chosen = {}
        for k, v in zip(keys, combo):
            _set(cfg, k, v)
            chosen[k] = v
        yield cfg, chosen


def run_eval(cfg: dict, tasks: list[str], cfg_path: Path) -> dict:
    """Escreve cfg num arquivo temporário, roda cada task, mede pass-rate e custo."""
    cfg_path.write_text(yaml.safe_dump(cfg))
    orch = Orchestrator(config_path=str(cfg_path))
    n_pass = 0
    total_cost = 0.0
    t0 = time.time()
    for t in tasks:
        try:
            r = orch.run(t)
            ok = all(sr.status == "ok" for sr in r.results)
            n_pass += int(ok)
            total_cost += r.total_cost_usd
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]eval task failed: {e}[/]")
    return {
        "pass_rate": n_pass / max(len(tasks), 1),
        "cost_usd": total_cost,
        "wall_time_s": time.time() - t0,
    }


def pareto_dominates(a: dict, b: dict) -> bool:
    """a domina b se a é >= em todas as dimensões e > em pelo menos uma."""
    return (
        a["pass_rate"] >= b["pass_rate"]
        and a["cost_usd"] <= b["cost_usd"]
        and a["wall_time_s"] <= b["wall_time_s"]
        and (a["pass_rate"] > b["pass_rate"] or a["cost_usd"] < b["cost_usd"])
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=8.0)
    p.add_argument("--mode", choices=["random", "grid"], default="random")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--eval-suite", default="eval/tasks.txt")
    p.add_argument("--out", default=".swarm/research/results.jsonl")
    args = p.parse_args()

    base = yaml.safe_load(open(args.config))
    tasks = [t.strip() for t in Path(args.eval_suite).read_text().splitlines() if t.strip()]
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    tmp_cfg = Path(".swarm/research/_tmp_config.yaml")
    tmp_cfg.parent.mkdir(parents=True, exist_ok=True)

    iterator = grid_iter(base) if args.mode == "grid" else iter(lambda: sample_cfg(base), None)
    deadline = time.time() + args.hours * 3600
    pareto: list[dict] = []

    while time.time() < deadline:
        cfg, chosen = next(iterator) if args.mode == "grid" else sample_cfg(base)
        score = run_eval(cfg, tasks, tmp_cfg)
        rec = {"chosen": chosen, "score": score, "ts": time.time()}
        with out.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        # atualiza Pareto front
        pareto = [p for p in pareto if not pareto_dominates(score, p["score"])]
        if not any(pareto_dominates(p["score"], score) for p in pareto):
            pareto.append(rec)
            console.print(f"[green]+ pareto[/] {chosen} -> {score}")

    console.print(f"\n[bold]Pareto front ({len(pareto)} configs):[/]")
    for p_ in pareto:
        console.print(f"  {p_['chosen']} -> {p_['score']}")


if __name__ == "__main__":
    main()
