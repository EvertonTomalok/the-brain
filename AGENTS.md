# AGENTS.md

> Instruções para qualquer agente (LLM ou humano) trabalhando neste repositório.
> Ler antes de propor planos ou abrir PRs.

## Como rodar

- Build: `<seu comando>`
- Testes: `<seu comando>`
- Lint: `ruff check .`
- Typecheck: `mypy .`
- Benchmark: `<seu comando, se houver>`

## Convenções

- Estilo: `ruff format` (line length 100).
- Tipos: anotar em todos os símbolos públicos.
- Erros: subclasses de `AppError` em `src/errors.py`. Nunca `except Exception:` sem re-raise.
- Logging: `logger = logging.getLogger(__name__)`. Sem `print` em código de produção.
- Async: prefira `asyncio.TaskGroup`. Justifique qualquer `threading`.

## Áreas sensíveis (escalação automática)

Tocar qualquer coisa abaixo dispara guardrails: `risk=high`, executor frontier, e **dois reviewers cross-vendor**.

- Autenticação / autorização — `src/auth/**`
- Pagamentos / billing — `src/billing/**`
- Criptografia / secrets — `src/crypto/**`, `.env*`
- Multi-tenant — qualquer mudança em `tenant_id`/`org_id`
- Migrações de schema — `migrations/**`, `alembic/**`
- Infra — `infra/**`, `docker/**`, `k8s/**`
- Concorrência — `asyncio`, `threading`, locks
- Deleção destrutiva — `DELETE FROM`, `drop_table`, `rm -rf`

## Política de PR

1. Toda mudança nasce em git worktree (`.swarm/wt/<id>`).
2. Verificação determinística (testes, lint, typecheck) antes do reviewer.
3. Reviewer cross-vendor obrigatório (executor X → reviewer Y).
4. Squash-merge na branch base. Sem merge commits.
5. PR_BODY gerado por `release_scribe` (escribir em `.swarm/PR_BODY_*.md`).
6. Áreas sensíveis: revisão humana obrigatória antes do merge.

## Para o Planner

- Write-set explícito em `files_to_touch`. Sem `**/*` ou `src/**`.
- `acceptance` SEMPRE inclui pelo menos 1 comando que prova o comportamento (não só lint).
- Subtasks devem ser paralelizáveis quando possível.

## Para o Executor

- Edite só o write-set.
- Patch mínimo.
- Rode `acceptance` antes de chamar `done`.
- Se precisar tocar área sensível, pare e escale.

## Para o Reviewer

- Verdict honesto. `approve` só se você mergearia em produção.
- Findings com arquivo/linha/severidade.
- Cross-vendor: nunca revise código gerado pelo seu próprio fornecedor.
