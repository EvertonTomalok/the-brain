# Pipeline atual de agentes para codificação

> Documento de referência fornecido pelo usuário (Everton, 2026-05-02). Usado como insumo para construir nanoswarm. Não editar.

(conteúdo original preservado abaixo — ver `ARCHITECTURE.md` e `config.yaml` para a versão integrada à pipeline.)

---

Atualizado em 2026-05-02. Foco: reduzir custo com modelos como Kimi, GLM e DeepSeek em tarefas simples/médias, preservando modelos frontier para planejamento, revisão crítica e decisões arquiteturais.

## Tese

A melhor pipeline não é "um agente grande faz tudo". É um sistema de roteamento por risco:

1. Ferramentas determinísticas primeiro: `rg`, AST, typecheck, testes, linters, formatters, coverage, benchmarks.
2. Modelos baratos para leitura, triagem, patches pequenos, refactors mecânicos e geração de testes simples.
3. Modelos fortes para planejamento, arquitetura, debugging difícil, revisão de segurança e síntese final.
4. Loop fechado estilo Karpathy: cada agente propõe, executa, mede e mantém apenas mudanças verificadas.
5. Worktrees isoladas para paralelismo; merge somente após validação.

## Papéis principais (resumo)

- **Router/Triage** (barato): classifica task_type, risco, escopo, validação.
- **Context Scout** (barato, read-only): mapeia repo, símbolos, padrões — nunca edita.
- **Planner** (frontier): plano 3–7 passos, write-set, critérios de aceite, comandos de validação.
- **Executor** (por risco): edita só o write-set, patch mínimo, valida.
- **Fixer**: 2 tentativas baratas, depois escala.
- **Reviewer cruzado** (vendor diferente do executor): correção, regressões, segurança, performance, testes.
- **Release Scribe** (barato): resumo do PR, arquivos, comandos, riscos residuais.

## Karpathy loop aplicado

- Humano define objetivo + métrica curta.
- Agente propõe mudança pequena → aplica → roda métrica → mantém ou reverte.
- Sem métrica, não roda loop autônomo longo.

## Guardrails

Escalar automaticamente para frontier + review duplo se tocar: auth/authorization, pagamentos, criptografia, multi-tenant, secrets, migração de dados, infra, concorrência, deleção, compliance.

## Endpoints específicos (úteis)

- Kimi (Anthropic-compatible): `https://api.moonshot.ai/anthropic` com `ANTHROPIC_MODEL=kimi-k2.6`
- GLM coding: `https://api.z.ai/api/coding/paas/v4`
- DeepSeek (Anthropic-compatible): `https://api.deepseek.com/anthropic`

## Métricas de sucesso

Custo médio por PR; taxa de sucesso sem escalamento; iterações até passar; % revertido pelo reviewer; regressões pós-merge; tempo até PR; cobertura em arquivos tocados; tokens por fase.

> Documento integrado a `ARCHITECTURE.md` (seções: Papéis, Roteamento por task_type, Guardrails, Plano de adoção, MVP, Karpathy loop).
