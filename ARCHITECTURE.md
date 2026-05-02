# nanoswarm — arquitetura

> Pipeline minimalista de agentes para codificação, no espírito do `nanochat` do Karpathy: poucos arquivos, sem mágica, fácil de auditar e modificar. Roteia tarefas por **risco × task_type** (Triage → Scout → Planner → Executor → Fixer → Reviewer cruzado → Release Scribe), isola execuções em git worktrees, e exige verificação executável + revisão **cross-vendor** antes de mergear.

Data de referência: maio de 2026. Integra o doc de referência [`refs/agent-coding-pipeline-2026.md`](./refs/agent-coding-pipeline-2026.md).

---

## 1. Princípios de design

1. **Determinístico antes de LLM.** `rg`, AST, typecheck, testes, lint, benchmark — só chama modelo onde ferramenta não resolve.
2. **Roteamento por risco.** Cada classe de tarefa (`docs`, `tests`, `frontend`, `backend_feature`, `auth_security_payments`, `data_migration`, `performance`) mapeia para o modelo mais barato que ainda passa nos verificadores.
3. **Cross-vendor review.** Reviewer **nunca** é do mesmo fornecedor que o executor. Executor Kimi → reviewer Claude/GPT. Executor GPT-5.5 → reviewer Claude/DeepSeek.
4. **Isolamento por padrão.** Toda execução de worker acontece num git worktree próprio. Concorrência sem conflito, rollback grátis.
5. **Verificação executável é o juiz.** "Parece certo" não conta — testes, type-check, lint, e um critic-LLM rápido (Haiku) decidem o merge.
6. **Memória em arquivo plano.** `decisions.md`, `facts.md`, `scratchpad.md`. Sem vector DB até medir necessidade — Karpathy-style.
7. **Karpathy loop opcional.** Loop meta que varia prompts/roteamento e mede contra suite de tarefas. Sem métrica, não roda loop autônomo longo.

---

## 2. Mapa dos modelos (maio/2026)

A tabela abaixo é o coração do roteador. Preços e benchmarks atualizados para abril–maio/2026.

### Frontier (planejamento, julgamento, alto risco)

| Modelo                  | Forte em                              | Quando usar                                                     |
| ----------------------- | ------------------------------------- | --------------------------------------------------------------- |
| `claude-opus-4-7`       | raciocínio profundo, design           | Planner principal, reviewer em high-stakes.                     |
| `claude-opus-4-6`       | balanço qualidade/preço               | Alternativa ao 4-7, ainda top-tier.                             |
| `claude-sonnet-4-6`     | re-planejamento, executor de risco    | Executor frontier mais barato; re-plan intra-tarefa.            |
| `gpt-5.5`               | coding agent geral                    | Planner/executor frontier alternativo (cross-vendor).           |
| `gpt-5.5-pro`           | tarefas difíceis longas               | Reservar para casos onde 5.5 falha.                             |
| `gpt-5.3-codex`         | edição de código longa                | Executor frontier para codebases grandes.                       |

### Capable barato (executor padrão)

| Modelo               | Preço (in/out, $/MTok)        | Notas                                                             |
| -------------------- | ----------------------------- | ----------------------------------------------------------------- |
| `kimi-k2.6`          | $0.60 / $2.50 (oficial)       | 256k ctx, JSON, tool calls, Anthropic-compatible. Agent Swarm.    |
| `glm-5.1`            | competitivo                   | 200k ctx, saída até 128k — flagship Z.AI para long-horizon.       |
| `glm-5`              | competitivo                   | Versão geral, ótima para context/scout.                           |
| `glm-4.6`            | $0.40 / $1.75                 | 200K ctx, 82.8% LCB v6, ~30% mais eficiente em tokens que 4.5.    |
| `deepseek-v4-pro`    | ~$0.30 / $1.20 (promo)        | 1M ctx, 80.6% SWE-bench. Promo até 2026-05-31 15:59 UTC.          |

### Rápido/barato (triage, fixer, scout, batch)

| Modelo                | Preço          | Notas                                                  |
| --------------------- | -------------- | ------------------------------------------------------ |
| `deepseek-v4-flash`   | ~$0.10 / $0.40 | 1M ctx, ótimo throughput.                              |
| `glm-4.7-flashx`      | barato         | Extremamente rápido para triage/sumarização.           |
| `gpt-5.4-mini`        | barato         | Triage/fixer com contexto OpenAI.                      |
| `gpt-5.4-nano`        | minúsculo      | Classificação binária, roteamento.                     |

### Critic/Judge (revisão de diff fast-path)

| Modelo               | Notas                                                                    |
| -------------------- | ------------------------------------------------------------------------ |
| `claude-haiku-4-5`   | Veredito em <1k tokens. Bom para fast-path do verifier.                  |
| `gpt-5.4-mini`       | Alternativa cross-vendor barata ao Haiku.                                |

### Local (zero custo marginal)

`glm-4.6` ou `deepseek-v4-flash` em vLLM/Ollama via `LOCAL_LLM_BASE_URL`. Útil para volume alto e/ou dados sensíveis.

---

## 3. Topologia (papéis × roteamento)

```
                                         ┌──────────────────┐
                                         │   Orchestrator   │
                                         └─────────┬────────┘
                                                   │ task
                                                   ▼
                                  ┌─────────────────────────────┐
                                  │   1. Triage (cheap)         │
                                  │   classify(task_type, risk) │
                                  └─────────────┬───────────────┘
                                                │ {type, risk, files?}
                                                ▼
                                  ┌─────────────────────────────┐
                                  │   2. Context Scout          │
                                  │   read-only mapping         │
                                  └─────────────┬───────────────┘
                                                │ symbols, callers, patterns
                                                ▼
                                  ┌─────────────────────────────┐
                                  │   3. Planner (frontier)     │
                                  │   plan + write-set + accept │
                                  └─────────────┬───────────────┘
                                                │ subtasks
                                                ▼
                                  ┌─────────────────────────────┐
                                  │   Router by risk × type     │
                                  │   -> alias                  │
                                  └────┬────────────┬───────────┘
                                       │            │
                                low/mid│            │high
                                       ▼            ▼
                          ┌──────────────┐  ┌──────────────────┐
                          │ Executor     │  │ Executor         │
                          │ kimi/glm/ds  │  │ frontier         │
                          │ (worktree)   │  │ (worktree)       │
                          └──────┬───────┘  └────────┬─────────┘
                                 └──────────┬────────┘
                                            ▼
                          ┌─────────────────────────────────────┐
                          │   Verifier (deterministic + critic) │
                          │   tests + ruff + mypy + Haiku       │
                          └────────┬───────────┬────────────────┘
                                   │ pass      │ fail
                                   ▼           ▼
                          ┌──────────────┐ ┌──────────────────┐
                          │  Reviewer    │ │  Fixer           │
                          │  CROSS-      │ │  cheap, max 2    │
                          │  VENDOR      │ │  attempts        │
                          └──────┬───────┘ └────────┬─────────┘
                                 │                  │
                          ┌──────┴───────┐    ┌─────┴─────────┐
                          │ approved     │    │ persists fail │
                          ▼              ▼    │               │
                   ┌────────────┐  ┌──────────┴───┐      ┌────▼────────┐
                   │ Release    │  │ Re-plan      │      │ Escalate to │
                   │ Scribe     │  │ (Sonnet)     │      │ frontier    │
                   │ (cheap)    │  └──────────────┘      └─────────────┘
                   └────────────┘
```

---

## 4. Componentes (1 arquivo por papel)

### 4.1 `gateway.py` — fachada única

`litellm` wrapper. Resolve aliases, retry com backoff, fallback automático, tracking de custo em `spend.jsonl`. Detalhes na seção 3 do código.

### 4.2 `router.py` — heurística + classifier opcional

Duas dimensões:

- **task_type**: `docs | tests | frontend | backend_feature | refactor | auth_security_payments | data_migration | performance | bug | docs`
- **risk**: `low | medium | high`

Decisão final: `tier_to_alias[type][risk] -> alias`. Mapeamento vive em `config.yaml`.

Heurística (cheap) primeiro; se ambíguo, chama um classifier `triage` (`deepseek-v4-flash` ou `gpt-5.4-nano`) que devolve JSON estruturado.

### 4.3 `scout.py` — Context Scout (read-only)

Modelo barato (`kimi-k2.6` ou `glm-5`). Permissões: só `read`, `grep`, `ls`, `git log -- file`. Nunca edita.

Devolve resumo curto:
- símbolos relevantes
- arquivos onde estão
- chamadores
- padrões de teste/estilo do projeto
- riscos potenciais

Não cola arquivos inteiros — aponta trechos. Esse passo evita jogar 200k+ tokens no executor.

### 4.4 `planner.py` — Claude/GPT decompõe

Recebe triage + scout. Devolve plano JSON com:
- `subtasks[i].description`
- `files_to_touch` (write-set, hard limit)
- `acceptance` (comandos shell que devem exit 0)
- `tier_hint`, `risk`

Modelo padrão: `claude-opus-4-7`. Fallback: `gpt-5.5`.

### 4.5 `worker.py` — executa subtask

Loop ReAct minimalista. Tools: `read`, `write`, `apply_patch`, `run`, `done`.

Modelo escolhido pelo router via `(task_type, risk)`.

Hard rule: `write` falha se path não está em `files_to_touch`.

### 4.6 `verifier.py` — testes + critic LLM

1. **Determinístico**: roda `acceptance` + `always_run` (`ruff`, etc.).
2. **Probabilístico**: passa `git diff` para `claude-haiku-4-5` (ou `gpt-5.4-mini` cross-vendor) com prompt de revisão rápida.

`fail` determinístico bloqueia. `fail` probabilístico bloqueia em high-stakes.

### 4.7 `reviewer.py` — cross-vendor reviewer

Diferente do critic do verifier. **Sempre de fornecedor diferente do executor**. Roda depois do verifier passar, antes do merge.

Mapping em `config.yaml`:

```yaml
review_pairs:
  anthropic_executor: openai/gpt-5.5     # ou deepseek-v4-pro
  openai_executor:    anthropic/claude-opus-4-7
  deepseek_executor:  anthropic/claude-opus-4-7  # ou openai/gpt-5.5
  moonshot_executor:  anthropic/claude-opus-4-7
  zai_executor:       openai/gpt-5.5
```

Revisão estruturada: correção, regressões, segurança, perf, simplicidade, testes suficientes. Saída JSON `{verdict: approve|request_changes|reject, findings: [...]}`.

### 4.8 `guardrails.py` — escalação automática

Lista de gatilhos que forçam upgrade para frontier + review duplo:

```python
GUARDRAIL_PATTERNS = {
    "auth":        [r"\bauth\b", r"login", r"oauth", r"jwt", r"session"],
    "payments":    [r"stripe", r"paypal", r"billing", r"invoice", r"payment"],
    "crypto":      [r"encrypt", r"decrypt", r"hash", r"crypto", r"key.?management"],
    "multitenant": [r"tenant", r"workspace_id", r"org_id"],
    "secrets":     [r"\.env", r"secret", r"api[_-]?key", r"token"],
    "migration":   [r"migration", r"alembic", r"schema_change"],
    "infra":       [r"terraform", r"kubernetes", r"docker.?compose"],
    "concurrency": [r"asyncio", r"threading", r"lock", r"mutex", r"race"],
    "deletion":    [r"DELETE FROM", r"drop_table", r"unlink"],
    "compliance":  [r"gdpr", r"pii", r"hipaa", r"license"],
}
```

Rodado contra: descrição da tarefa, lista de arquivos, e diff (após executor). Match → escala antes de mergear.

### 4.9 `release_scribe.py` — resumo do PR

Modelo barato (`gpt-5.4-mini` ou `glm-4.7-flashx`). Recebe:
- plano original
- subtasks executadas + verdicts
- diff agregado
- comandos rodados + outputs

Devolve `PR_BODY.md`:
- O quê
- Por quê
- Arquivos tocados
- Comandos rodados + resultados
- Riscos residuais

### 4.10 `worktree.py`, `memory.py`, `orchestrator.py`

Já documentados no PR original (worktrees descartáveis, memory em arquivos planos, laço principal). O `orchestrator` agora chama Triage → Scout → Planner → Worker → Verifier → Reviewer → Scribe.

### 4.11 `auto_research.py` — Karpathy loop

Espaço de busca: thresholds do router, escolhas de alias por tier, strictness do critic. Métrica: `pass_rate × cost × wall_time` em uma `eval/tasks.txt` curada. Salva Pareto-front em `.swarm/research/results.jsonl`.

**Regra de ouro**: sem métrica curta e estável, não rode. Mesmo padrão do `karpathy/autoresearch`.

---

## 5. Roteamento por task_type (config canônica)

```yaml
routing:
  docs:                       { plan: false, executor: low,  review: optional }
  tests:                      { plan: false, executor: med,  review: required_if_test_semantics_change }
  frontend:                   { plan: true,  executor: med,  review: visual_and_accessibility }
  backend_feature:            { plan: true,  executor: med,  review: required }
  refactor:                   { plan: true,  executor: med,  review: required }
  bug:                        { plan: true,  executor: med,  review: required }
  performance:                { plan: true,  executor: med,  review: benchmark_required }
  auth_security_payments:     { plan: true,  executor: high, review: required_two_models }
  data_migration:             { plan: true,  executor: high, review: required_two_models }
```

`low | med | high` → mapeiam para alias via `models.implementation_low/med/high`.

---

## 6. Cross-vendor review — por que importa

Modelos do mesmo fornecedor compartilham viés de treinamento. Um Opus revisando código de outro Opus deixa passar os mesmos buracos sistemáticos. Cross-vendor review:

- **Pega assunções diferentes.** GPT pode notar problemas de async que Claude não enfatiza, e vice-versa.
- **Vetores de ataque distintos.** Se um modelo foi atacado via prompt injection no executor, outro fornecedor é menos provável de cair no mesmo ataque.
- **Calibração honesta.** Reviewer treinado em outra base é mais provável de discordar quando deve discordar.

Em high-stakes (`auth_security_payments`, `data_migration`), exigimos **dois reviewers cross-vendor distintos**.

---

## 7. Guardrails de escalação automática

Disparados se a descrição da tarefa, files_to_touch, ou o diff resultante baterem qualquer padrão de `guardrails.py`. Efeitos:

1. Forçar `risk = high` no router.
2. Trocar executor para `implementation_high`.
3. Exigir reviewer cross-vendor (e dois em casos críticos).
4. Bloquear `auto_merge` — exigir revisão humana.
5. Marcar `release_scribe` para destacar a área sensível no PR.

---

## 8. Karpathy loop aplicado a coding

| Caso              | Métrica curta                        | Loop                                                |
| ----------------- | ------------------------------------ | --------------------------------------------------- |
| Bug               | teste de reprodução passa            | patch → roda teste → mantém/reverte                 |
| Performance       | benchmark melhora sem regressão      | otimização → benchmark → comparar                   |
| Frontend          | snapshot/visual eval/axe passa       | UI change → eval → mantém/reverte                   |
| Prompt/skill      | dataset de eval melhora              | mudar prompt → rodar eval → mantém/reverte          |
| Refactor          | testes + typecheck OK + diff menor   | refactor pequeno → validação → mantém/reverte       |
| Pipeline (meta)   | pass_rate × cost × latency Pareto    | varia config router → roda eval suite → Pareto-set  |

Espelha exatamente o que `karpathy/autoresearch` (mar/2026) fez ao deixar agente rodando 2 dias sobre `nanochat` e descobrir ~20 melhorias (-11% no Time-to-GPT-2). A mesma forma serve para qualquer alvo mensurável.

---

## 9. Modos de operação

### 9.1 Codegen massivo

`triage` → (skip scout/planner se template) → `worker_swarm` (Kimi K2.6, até 300 sub-agents) → verifier → opcional scribe.
Custo típico: <$2 para 80 componentes.

### 9.2 Refactor automatizado

`triage` → `scout` (Kimi/GLM-5) → `planner` (Opus 4.7) → `worker_med` (DeepSeek-Pro/GLM-5.1) por subtask → verifier → **reviewer cross-vendor** (GPT-5.5) → scribe.

### 9.3 Pipeline de revisão de PR (CI bot)

`triage` → `scout` → **reviewer cross-vendor** sobre o diff → comenta findings no PR. Sem executor — só análise.

### 9.4 Pesquisa/aprendizado (estilo nanochat)

`auto_research.py` rodando overnight contra `eval/tasks.txt`. Pareto-front em `(pass_rate, cost, wall_time)`.

---

## 10. Plano de adoção em 7 dias

| Dia | Foco             | Entregáveis                                                        |
| --- | ---------------- | ------------------------------------------------------------------ |
| 1   | Baseline         | Comandos test/lint/build do repo. `AGENTS.md`. Modelos disponíveis.|
| 2   | Router           | Prompt JSON de triage. Rodar em 20 issues antigas. Medir economia. |
| 3   | Context Scout    | Agente read-only padronizado. Saída com símbolos, riscos.          |
| 4   | Executor barato  | Tarefas docs/test/refactor com Kimi/GLM/DeepSeek. Medir 1ª-pass.   |
| 5   | Reviewer cruzado | Revisar patches baratos com GPT/Claude. Catalogar erros recorrentes.|
| 6   | Karpathy loop    | Escolher alvo mensurável. Rodar com orçamento fixo. Manter Pareto. |
| 7   | Automação        | YAML de roteamento. Scripts de validação. Dashboard de custo/sucesso.|

---

## 11. MVP — 5 agentes

```text
issue → triage-cheap → context-scout → planner → executor-medium → tests → reviewer-cross → final
```

| Papel             | Modelo sugerido (default)         | Cross-vendor backup        |
| ----------------- | --------------------------------- | -------------------------- |
| triage-cheap      | `deepseek-v4-flash`               | `gpt-5.4-nano`             |
| context-scout     | `kimi-k2.6` ou `glm-5`            | `deepseek-v4-flash`        |
| planner           | `claude-opus-4-7` ou `gpt-5.5`    | o outro                    |
| executor-medium   | `kimi-k2.6` ou `glm-5.1`          | `deepseek-v4-pro`          |
| reviewer-cross    | `gpt-5.5` (se executor é Anthr.)  | `claude-opus-4-7` se exec. é OpenAI |

Atalhos:

- Tarefa trivial → `triage` → `executor-cheap` → `tests` → final.
- Tarefa crítica → `scout` → `planner-frontier` → `executor-frontier` → `tests` → `reviewer-frontier-vendor-2` → final.

---

## 12. Custo esperado (ordem de grandeza)

100 tarefas de codegen "padrão" (~5k in / 2k out por tarefa, 1 sub-tarefa cada):

| Stack                                        | Custo estimado (100 tarefas) |
| -------------------------------------------- | ---------------------------- |
| 100% Claude Opus 4-7                         | ~$15–20                      |
| 100% Sonnet 4-6                              | ~$3–5                        |
| Planner Opus + worker GLM-4.6                | **~$0.60–1.00**              |
| Triage→Scout→Planner→Kimi K2.6 + GPT review  | ~$0.80–1.50                  |
| Tudo local (vLLM + GLM-4.6) + Claude review  | ~$0.10 (só review)           |

A política completa (com scout, cross-vendor review e scribe) custa um pouco mais que a stack mínima — mas reduz drasticamente regressões e retrabalho. **Reviewer cruzado paga por si próprio** ao bloquear merges defeituosos.

---

## 13. Métricas operacionais

Loggar em `metrics.csv`:

- custo médio por PR
- taxa de sucesso sem escalamento
- iterações até testes passarem
- % de diffs `request_changes`/`reject` pelo reviewer
- regressões pós-merge
- tempo até PR pronto
- tokens por fase
- distribuição de uso por modelo

---

## 14. Endpoints prontos (atalhos copy-paste)

### Kimi como Claude Code drop-in

```bash
export ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic
export ANTHROPIC_AUTH_TOKEN=$MOONSHOT_API_KEY
export ANTHROPIC_MODEL=kimi-k2.6
export CLAUDE_CODE_SUBAGENT_MODEL=kimi-k2.6
```

### GLM coding endpoint

```python
from openai import OpenAI
client = OpenAI(api_key=ZAI_KEY, base_url="https://api.z.ai/api/coding/paas/v4")
```

### DeepSeek Anthropic-compatible

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_API_KEY
export ANTHROPIC_MODEL=deepseek-v4-pro
```

---

## 15. Por que **não** LangGraph / CrewAI / AutoGen (e quando sim)

A favor: padrões prontos, observabilidade, integrações.
Contra: opacidade, latência extra, custo cognitivo de debug.

Para os 4 modos de operação descritos, a stack minimalista entrega os mesmos padrões em ~800 linhas auditáveis. Para >10 agentes em produção, com requisitos pesados de observabilidade (tracing distribuído, replay), considerar LangGraph.

---

## 16. O que **não** está na v1 (intencional)

- Vector DB / RAG. Adiar até medir necessidade.
- UI. Use o terminal.
- MCP servers customizados. Tools chamadas Python diretas — adicione MCP quando precisar expor a outros sistemas.
- Treinamento/fine-tuning.
- Multi-tenant / segurança forte. É single-user dev tool.
- Auto-merge em `main` para qualquer task com guardrail acionado — sempre exige revisão humana.

---

## 17. Referências

- [karpathy/nanochat](https://github.com/karpathy/nanochat) — minimalismo arquitetural.
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — agentes que melhoram código sozinhos.
- [DeepSeek V4 specs](https://www.nxcode.io/resources/news/deepseek-v4-release-specs-benchmarks-2026) e [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing).
- [Kimi K2.6 docs](https://platform.kimi.ai/docs/models) e [pricing](https://platform.kimi.ai/docs/pricing/chat-k26).
- [GLM-4.6 review](https://intuitionlabs.ai/articles/glm-4-6-open-source-coding-model) e [GLM-5.1 docs](https://docs.z.ai/guides/llm/glm-5.1).
- [OpenAI Models](https://developers.openai.com/api/docs/models) e [Agent orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration).
- [Claude subagents](https://claude.com/blog/subagents-in-claude-code) e [Claude Code model config](https://code.claude.com/docs/en/model-config).
- [Agent Architecture Patterns 2026](https://www.digitalapplied.com/blog/agent-architecture-patterns-taxonomy-2026).
- [Code Agent Orchestra — Addy Osmani](https://addyosmani.com/blog/code-agent-orchestra/).
- [LiteLLM Router](https://docs.litellm.ai/docs/routing).
- [refs/agent-coding-pipeline-2026.md](./refs/agent-coding-pipeline-2026.md) — doc de referência fornecido pelo usuário.
