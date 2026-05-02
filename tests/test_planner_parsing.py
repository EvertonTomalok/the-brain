"""Tests do parser de plano — sem rede."""
from __future__ import annotations

from nanoswarm.planner import _extract_json, _parse_plan


def test_extract_json_fenced():
    raw = '```json\n{"a": 1}\n```'
    assert _extract_json(raw) == {"a": 1}


def test_extract_json_with_prose():
    raw = "Sure! Here is the plan:\n{\"a\": 1, \"b\": [2, 3]}\nThanks."
    assert _extract_json(raw) == {"a": 1, "b": [2, 3]}


def test_parse_plan_fallback_when_empty():
    plan = _parse_plan("do thing", "no json here")
    assert len(plan.subtasks) == 1
    assert plan.subtasks[0].description == "do thing"


def test_parse_plan_happy():
    raw = '{"rationale": "ok", "subtasks": [{"id":"s1","description":"d","files_to_touch":["a.py"],"acceptance":["pytest a"],"tier_hint":"standard"}]}'
    plan = _parse_plan("t", raw)
    assert len(plan.subtasks) == 1
    assert plan.subtasks[0].id == "s1"
    assert plan.subtasks[0].acceptance == ["pytest a"]
