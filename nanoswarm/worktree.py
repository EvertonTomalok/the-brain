"""Helpers para git worktrees descartáveis. Cada subtask roda no seu."""
from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path
from typing import Iterator


def _git(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


def base_branch(repo: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)


@contextlib.contextmanager
def scoped(
    subtask_id: str,
    repo: Path = Path("."),
    base_dir: str = ".swarm/wt",
    branch_prefix: str = "swarm/",
    cleanup: bool = True,
) -> Iterator[Path]:
    """Cria worktree em base_dir/<id>, faz cleanup automático.

    Uso:
        with worktree.scoped("s1") as wt:
            ...                # mexer em wt
            # ao sair: opcionalmente merge() antes; sempre cleanup.
    """
    wt_path = (repo / base_dir / subtask_id).resolve()
    branch = f"{branch_prefix}{subtask_id}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    base = base_branch(repo)
    _git(["worktree", "add", "-b", branch, str(wt_path), base], cwd=repo)
    try:
        yield wt_path
    finally:
        if cleanup:
            try:
                _git(["worktree", "remove", "--force", str(wt_path)], cwd=repo)
            except subprocess.CalledProcessError:
                shutil.rmtree(wt_path, ignore_errors=True)
            try:
                _git(["branch", "-D", branch], cwd=repo)
            except subprocess.CalledProcessError:
                pass


def commit_all(wt: Path, message: str) -> str:
    _git(["add", "-A"], cwd=wt)
    try:
        _git(["commit", "-m", message], cwd=wt)
    except subprocess.CalledProcessError:
        return ""  # nada para commitar
    return _git(["rev-parse", "HEAD"], cwd=wt)


def merge_into_base(wt: Path, repo: Path = Path(".")) -> None:
    """Squash-merge a branch do worktree na branch base do repo."""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt)
    base = base_branch(repo)
    _git(["checkout", base], cwd=repo)
    _git(["merge", "--squash", branch], cwd=repo)
    _git(["commit", "-m", f"swarm merge {branch}"], cwd=repo)
