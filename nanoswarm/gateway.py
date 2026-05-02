"""Fachada única para todos os modelos via litellm.

Resolve aliases (planner/worker_std/critic) para o modelo real configurado em
config.yaml, faz retry com backoff, fallback automático, e registra custo.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm
import yaml
from dotenv import load_dotenv

load_dotenv()

# Falhar rápido em caso de chave inválida em vez de logar e seguir.
litellm.drop_params = True
litellm.set_verbose = False


@dataclass
class CallResult:
    text: str
    raw: Any
    cost_usd: float
    model: str
    in_tokens: int
    out_tokens: int


class Gateway:
    """Wrapper sobre litellm.completion com aliases, fallback e tracking de custo."""

    def __init__(self, config_path: str | Path = "config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.models = self.cfg["models"]
        self.spend_log = Path(self.cfg.get("memory", {}).get("dir", ".swarm/memory")) / "spend.jsonl"
        self.spend_log.parent.mkdir(parents=True, exist_ok=True)

    # --- chamada principal ------------------------------------------------- #
    def call(
        self,
        alias: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        max_retries: int = 3,
    ) -> CallResult:
        """Chama o modelo associado a `alias`. Retry + fallback automáticos."""
        spec = self._resolve(alias)
        attempts = [spec]
        if spec.get("fallback"):
            attempts.append({**spec, "model": spec["fallback"]})

        last_err: Exception | None = None
        for spec_try in attempts:
            for attempt in range(max_retries):
                try:
                    return self._do_call(alias, spec_try, messages, tools)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    sleep = 2**attempt
                    time.sleep(sleep)
        assert last_err is not None
        raise last_err

    # --- internos ---------------------------------------------------------- #
    def _resolve(self, alias: str) -> dict:
        if alias not in self.models:
            raise KeyError(f"alias '{alias}' não está em config.yaml")
        spec = dict(self.models[alias])
        # expandir ${ENV_VAR}
        for k, v in list(spec.items()):
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                spec[k] = os.environ.get(v[2:-1], "")
        return spec

    def _do_call(
        self, alias: str, spec: dict, messages: list[dict], tools: list[dict] | None
    ) -> CallResult:
        kwargs: dict[str, Any] = {
            "model": spec["model"],
            "messages": messages,
            "max_tokens": spec.get("max_tokens", 4096),
            "temperature": spec.get("temperature", 0.2),
        }
        if spec.get("api_base"):
            kwargs["api_base"] = spec["api_base"]
        if spec.get("api_key"):
            kwargs["api_key"] = spec["api_key"]
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = litellm.completion(**kwargs)
        msg = resp["choices"][0]["message"]
        text = msg.get("content") or ""
        usage = resp.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0

        self._log_spend(alias, spec["model"], in_tok, out_tok, cost)
        return CallResult(
            text=text, raw=resp, cost_usd=cost, model=spec["model"],
            in_tokens=in_tok, out_tokens=out_tok,
        )

    def _log_spend(self, alias: str, model: str, in_t: int, out_t: int, cost: float) -> None:
        rec = {
            "ts": time.time(),
            "alias": alias,
            "model": model,
            "in_tokens": in_t,
            "out_tokens": out_t,
            "cost_usd": cost,
        }
        with self.spend_log.open("a") as f:
            f.write(json.dumps(rec) + "\n")
