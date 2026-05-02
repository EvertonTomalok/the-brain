# nanoswarm

> Pipeline minimalista de agentes para coding (~1k linhas, sem framework).
> Roteia tarefas por **risco × task_type** com 7 papéis claros, isola em git
> worktrees, valida com testes + critic + **reviewer cross-vendor**, e escala
> automaticamente em áreas sensíveis (auth, pagamentos, crypto, migrações…).

Inspirado em [`karpathy/nanochat`](https://github.com/karpathy/nanochat) (minimalismo) e [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) (auto-melhoria mensurável).
Síntese das melhores práticas de coding agents em maio/2026 (ver [`refs/agent-coding-pipeline-2026.md`](./refs/agent-coding-pipeline-2026.md) e [`ARCHITECTURE.md`](./ARCHITECTURE.md)).

## TL;DR de custo

100 tarefas de codegen padrão: ~$0.80–1.50 com a pipeline completa (Triage → Scout → Opus planner → Kimi/GLM executor → GPT review). vs ~$15–20 com Opus puro. **~10–25× mais barato, mantendo a qualidade do plano e ganhando review independente.**

## Pipeline em 7 papéis

```
issue → triage → scout → planner → executor → verifier → reviewer (cross-vendor) → scribe → PR
```

| Papel             | Modelo (default)                  | Custo  | Por quê                                                |
| ----------------- | --------------------------------- | ------ | ------------------------------------------------------ |
| triage            | `deepseek-v4-flash`               | mínimo | classifica `task_type` + `risk` em <500 tokens         |
| context-scout     | `kimi-k2.6` (read-only)           | baixo  | mapeia repo, símbolos, padrões, riscos                 |
| planner           | `claude-opus-4-7`                 | alto   | plano com write-set + acceptance executável            |
| executor (med)    | `kimi-k2.6` ou `glm-5.1`          | baixo  | implementa em worktree isolado                         |
| executor (high)   | `claude-opus-4-7` ou `gpt-5.5`    | alto   | só em high-risk ou guardrails                          |
| verifier          | testes + ruff + `claude-haiku-4-5`| mínimo | fast-path determinístico + critic sobre diff           |
| reviewer cross-V  | vendor ≠ executor (auto-pick)     | médio  | review honesto, evita bias do mesmo treinamento        |
| release scribe    | `gpt-5.4-mini`                    | mínimo | gera `PR_BODY.md` com riscos residuais                 |

## Quickstart

```bash
pip install -e .
cp .env.example .env  # ANTHROPIC_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY…

# Tarefa única (pipeline completo)
python -m nanoswarm "extract UserService from src/legacy/users.py and update call sites"

# Codegen massivo (Kimi K2.6 Agent Swarm)
python examples/codegen_components.py specs/*.json

# Auto-research overnight (Karpathy-style)
python -m nanoswarm.auto_research --hours 8
```

## Estrutura

```
nanoswarm/
  gateway.py        litellm wrapper, fallbacks, custo
  router.py         (task_type, risk) -> alias
  triage.py         classificador barato em 1 chamada
  scout.py          read-only context mapper
  planner.py        Claude/GPT decompõe em subtasks
  worker.py         executa subtask em worktree isolado
  verifier.py       testes + lint + critic Haiku (fast-path)
  reviewer.py       cross-vendor reviewer (1 ou 2)
  guardrails.py     padrões de escalação automática
  release_scribe.py gera PR_BODY
  memory.py         arquivos planos: facts/decisions/spend
  worktree.py       git worktree helpers
  orchestrator.py   laço principal
  auto_research.py  busca configs Pareto-ótimas
prompts/            planner, scout, reviewer, critic
config.yaml         modelos + roteamento + guardrails
AGENTS.md           contrato pra qualquer agente no repo-alvo
```

## Cross-vendor review (por que importa)

Mesmo fornecedor compartilha viés de treinamento. Opus revisando Opus deixa passar buracos sistemáticos. nanoswarm escolhe automaticamente um reviewer de **outro fornecedor**:

| Executor                   | Reviewer (default)         |
| -------------------------- | -------------------------- |
| Claude (Anthropic)         | GPT-5.5 (OpenAI)           |
| GPT-5.5 (OpenAI)           | Claude Opus (Anthropic)    |
| DeepSeek V4-Pro            | Claude Opus (Anthropic)    |
| Kimi K2.6 (Moonshot)       | Claude Opus (Anthropic)    |
| GLM-5.1 (Z.AI)             | GPT-5.5 (OpenAI)           |

Em high-stakes (auth/payments/migration), exige **dois reviewers cross-vendor**.

## Guardrails de escalação automática

Padrões em `guardrails.py` — se a tarefa, files ou diff mencionarem qualquer um:

`auth · payments · crypto · multitenant · secrets · migration · infra · concurrency · deletion · compliance`

→ `risk=high`, executor frontier, 2 reviewers, **auto-merge bloqueado**.

## Karpathy loop (opcional)

`auto_research.py` deixa um meta-agente variando configs (thresholds do router, escolhas de executor, strictness do critic) e medindo contra `eval/tasks.txt`. Salva Pareto-front em `(pass_rate, cost, wall_time)`. Mesma ideia de [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch) — agente descobre melhorias sozinho durante a noite.

## Trocar modelo é uma linha

Tudo em `config.yaml`. Quer testar GPT-5.5 como planner? Mude `models.planner.model`. Quer Kimi como executor padrão? Mude `models.implementation_medium.model`. Sem tocar código.

## Próximos passos

Ver [`ARCHITECTURE.md`](./ARCHITECTURE.md) para racional completo, comparações de modelos (DeepSeek V4 / GLM-5.1 / Kimi K2.6 / Claude 4-7 / GPT-5.5), tabela de custos, plano de adoção em 7 dias e o MVP de 5 agentes.

## Status

Proof of concept didático. Para uso em produção, adicionar: rate limiting por chave, sandboxing real do `run()` (Firejail/gVisor), métricas de regressão pós-merge, e revisão humana obrigatória em qualquer task com guardrail acionado.
