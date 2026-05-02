"""Router por (task_type, risk) — combina heurística cheap + triage LLM.

API:
    router.classify(task, files) -> Tier            (heurística simples, legacy)
    router.choose_executor(triage, guardrails) -> alias
    router.policy_for(triage) -> dict do `routing[task_type]`
"""
from __future__ import annotations

from .gateway import Gateway
from .types import Tier


class Router:
    def __init__(self, gateway: Gateway):
        self.gw = gateway
        self.cfg = gateway.cfg["router"]
        self.routing = gateway.cfg.get("routing", {})

    # ── API legacy (heurística direta para tier) ─────────────────────────── #
    def classify(self, task: str, files: list[str] | None = None) -> Tier:
        task_lc = task.lower()
        files = files or []
        if any(k in task_lc for k in self.cfg["trivial_keywords"]):
            return Tier.TRIVIAL
        if len(files) > self.cfg["complex_threshold_files"]:
            return Tier.COMPLEX
        if any(k in task_lc for k in self.cfg["complex_keywords"]):
            return Tier.COMPLEX
        return Tier.STANDARD

    def alias_for(self, tier: Tier) -> str:
        # legacy mapping kept for backwards compat with older configs
        legacy = self.cfg.get("tier_to_alias")
        if legacy:
            return legacy[tier.value]
        # fallback: usa implementation_*
        return {
            Tier.TRIVIAL: "implementation_low",
            Tier.STANDARD: "implementation_medium",
            Tier.COMPLEX: "implementation_high",
        }[tier]

    # ── API nova: routing por task_type ──────────────────────────────────── #
    def policy_for(self, task_type: str) -> dict:
        """Devolve a política do `routing[task_type]` ou um default seguro."""
        return self.routing.get(task_type, self.routing.get("backend_feature", {
            "plan": True, "executor": "implementation_medium", "review": "required",
        }))

    def choose_executor(
        self,
        task_type: str,
        risk: str,
        *,
        guardrail_categories: set[str] | None = None,
    ) -> str:
        """Decide o alias do executor considerando task_type, risk e guardrails."""
        # Guardrails forçam tudo a high
        if guardrail_categories:
            return "implementation_high"

        # Política base do routing
        policy = self.policy_for(task_type)
        base_alias = policy.get("executor", "implementation_medium")

        # Risk override: high sempre escala
        if risk == "high":
            return "implementation_high"
        if risk == "low" and base_alias == "implementation_medium":
            # docs/test triviais ficam baratos
            if task_type in {"docs", "tests"}:
                return "implementation_low"
        return base_alias

    def review_required(
        self,
        task_type: str,
        *,
        guardrail_categories: set[str] | None = None,
    ) -> str:
        """Devolve a string de política de review (required, optional, two_models...)."""
        if guardrail_categories:
            return "required_two_models"
        return self.policy_for(task_type).get("review", "required")
