# the-brain (nanoswarm)

> A minimalist multi-model coding agent pipeline (~1.7k lines, no framework).
> Routes tasks by **risk × task_type** across 7 explicit roles, isolates work
> in git worktrees, validates with tests + critic + **cross-vendor reviewer**,
> and auto-escalates anything touching auth, payments, crypto, migrations, etc.

Inspired by [`karpathy/nanochat`](https://github.com/karpathy/nanochat) (architectural minimalism) and [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) (autonomous self-improvement against a measurable metric). Synthesizes the state of coding agents as of May 2026 — see [`refs/agent-coding-pipeline-2026.md`](./refs/agent-coding-pipeline-2026.md) and [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## TL;DR on cost

100 standard codegen tasks: **~$0.80–1.50** with the full pipeline (Triage → Scout → Opus planner → Kimi/GLM executor → GPT review) vs ~$15–20 with pure Opus. **~10–25× cheaper while keeping plan quality and gaining independent review.**

## Pipeline in 7 roles

```
issue → triage → scout → planner → executor → verifier → reviewer (cross-vendor) → scribe → PR
```

| Role              | Default model                       | Cost    | Why                                                       |
| ----------------- | ----------------------------------- | ------- | --------------------------------------------------------- |
| triage            | `deepseek-v4-flash`                 | minimal | classifies `task_type` + `risk` in <500 tokens            |
| context-scout     | `kimi-k2.6` (read-only)             | low     | maps the repo: symbols, patterns, risks                   |
| planner           | `claude-opus-4-7`                   | high    | plan with explicit write-set + executable acceptance      |
| executor (med)    | `kimi-k2.6` or `glm-5.1`            | low     | implements in an isolated worktree                        |
| executor (high)   | `claude-opus-4-7` or `gpt-5.5`      | high    | only for high-risk subtasks or guardrail hits             |
| verifier          | tests + ruff + `claude-haiku-4-5`   | minimal | deterministic fast-path + critic over the diff            |
| reviewer cross-V  | vendor ≠ executor (auto-picked)     | medium  | honest review, avoids same-vendor training bias           |
| release scribe    | `gpt-5.4-mini`                      | minimal | writes `PR_BODY.md` with residual risks                   |

## Quickstart

```bash
pip install -e .
cp .env.example .env  # ANTHROPIC_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY…

# Single task — full pipeline
python -m nanoswarm "extract UserService from src/legacy/users.py and update call sites"

# Bulk codegen (uses Kimi K2.6 Agent Swarm)
python examples/codegen_components.py specs/*.json

# Karpathy-style overnight auto-research
python -m nanoswarm.auto_research --hours 8
```

## Layout

```
nanoswarm/
  gateway.py        litellm wrapper, fallbacks, cost tracking
  router.py         (task_type, risk) -> model alias
  triage.py         cheap classifier (one call)
  scout.py          read-only context mapper
  planner.py        Claude/GPT decomposes into subtasks
  worker.py         executes a subtask inside an isolated worktree
  verifier.py       tests + lint + Haiku critic (fast-path)
  reviewer.py       cross-vendor reviewer (1 or 2)
  guardrails.py     auto-escalation patterns
  release_scribe.py generates PR_BODY
  memory.py         flat files: facts/decisions/spend
  worktree.py       git worktree helpers
  orchestrator.py   main loop
  auto_research.py  searches for Pareto-optimal configs
prompts/            planner, scout, reviewer, critic
config.yaml         models + routing + guardrails
AGENTS.md           contract for any agent operating in the target repo
```

## Cross-vendor review (why it matters)

Models from the same vendor share training biases. Opus reviewing Opus lets the same systematic blind spots through. nanoswarm automatically picks a reviewer from a **different vendor**:

| Executor                   | Default reviewer              |
| -------------------------- | ----------------------------- |
| Claude (Anthropic)         | GPT-5.5 (OpenAI)              |
| GPT-5.5 (OpenAI)           | Claude Opus (Anthropic)       |
| DeepSeek V4-Pro            | Claude Opus (Anthropic)       |
| Kimi K2.6 (Moonshot)       | Claude Opus (Anthropic)       |
| GLM-5.1 (Z.AI)             | GPT-5.5 (OpenAI)              |

For high-stakes work (auth/payments/migration), **two cross-vendor reviewers are required**.

## Auto-escalation guardrails

Patterns in `guardrails.py` — if the task description, file paths, or resulting diff mention any of these:

`auth · payments · crypto · multitenant · secrets · migration · infra · concurrency · deletion · compliance`

→ `risk=high`, frontier executor, two reviewers, **auto-merge blocked** (manual review required).

## Karpathy loop (optional)

`auto_research.py` runs a meta-agent that varies configs (router thresholds, executor choices per tier, critic strictness) and measures them against `eval/tasks.txt`. It saves the Pareto front in `(pass_rate, cost, wall_time)` to `.swarm/research/results.jsonl`. Same idea as [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) — agents discover improvements on their own overnight.

## Switching models is one line

Everything lives in `config.yaml`. Want to test GPT-5.5 as planner? Change `models.planner.model`. Want Kimi as the default executor? Change `models.implementation_medium.model`. No code changes.

## Models supported (May 2026)

**Frontier** (planning, judgment, high-risk execution)
- `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`
- `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.3-codex`

**Capable & cheap** (default executors)
- `kimi-k2.6` — 256k ctx, JSON, tool calls, Anthropic-compatible endpoint, Agent Swarm (up to 300 sub-agents)
- `glm-5.1` — 200k ctx, 128k output, Z.AI flagship for long-horizon coding
- `glm-4.6` — 200k ctx, 82.8% LCB v6, ~30% more token-efficient than 4.5
- `deepseek-v4-pro` — 1M ctx, 80.6% SWE-bench (statistically tied with Opus 4.7)

**Fast & cheap** (triage, fixer, scout, batch)
- `deepseek-v4-flash`, `glm-4.7-flashx`, `gpt-5.4-mini`, `gpt-5.4-nano`

**Critic / fast-path judge**
- `claude-haiku-4-5`, `gpt-5.4-mini`

**Local** — `glm-4.6` or `deepseek-v4-flash` on vLLM/Ollama via `LOCAL_LLM_BASE_URL`.

## Next steps

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full rationale: model comparisons, cost tables, the 7-day adoption plan, and the 5-agent MVP.

## Status

Didactic proof of concept. For production use, add: per-key rate limiting, real sandboxing for `run()` (Firejail/gVisor), post-merge regression metrics, and mandatory human review for any task that triggers a guardrail.
