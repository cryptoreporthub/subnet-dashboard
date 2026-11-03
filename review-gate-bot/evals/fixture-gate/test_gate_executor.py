"""Fail-closed gate executor resolution (R0-REVIEW-3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from gate_core import resolve_gate_python

REPO = Path(__file__).resolve().parents[3]


def test_gate_executor_resolves_without_repo_venv() -> None:
    """pytest + pytest-shard must be locatable (bootstrap pip if needed), never silently skipped."""
    _py, errors = resolve_gate_python(REPO, bootstrap=True)
    assert not errors, errors
