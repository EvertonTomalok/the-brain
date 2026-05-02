"""Smoke tests do router — sem rede, só heurística."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nanoswarm.router import Router
from nanoswarm.types import Tier

CFG = """
models: {}
router:
  trivial_keywords: [rename, format, docstring, typo, comment]
  complex_threshold_files: 3
  complex_keywords: [refactor, redesign, migrate, architecture]
  tier_to_alias:
    trivial: worker_swarm
    standard: worker_std
    complex: worker_heavy
  ask_critic_when_ambiguous: false
"""


class FakeGW:
    def __init__(self):
        self.cfg = yaml.safe_load(CFG)


@pytest.fixture
def router(tmp_path: Path) -> Router:
    return Router(FakeGW())  # type: ignore[arg-type]


def test_trivial_by_keyword(router):
    assert router.classify("rename foo to bar in src/baz.py", ["src/baz.py"]) == Tier.TRIVIAL


def test_complex_by_keyword(router):
    assert router.classify("refactor user module", ["src/u.py"]) == Tier.COMPLEX


def test_complex_by_files(router):
    files = ["a.py", "b.py", "c.py", "d.py"]
    assert router.classify("update headers", files) == Tier.COMPLEX


def test_standard_default(router):
    assert router.classify("implement parse_csv", ["src/csv.py"]) == Tier.STANDARD


def test_alias_for(router):
    assert router.alias_for(Tier.TRIVIAL) == "worker_swarm"
    assert router.alias_for(Tier.STANDARD) == "worker_std"
    assert router.alias_for(Tier.COMPLEX) == "worker_heavy"
