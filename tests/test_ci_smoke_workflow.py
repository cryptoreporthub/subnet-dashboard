"""Guard: ci-smoke.yml PR trigger and permissions match issue #1624 PR 0."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci-smoke.yml"


def _load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(wf):
    return wf.get("on", wf.get(True))


def test_ci_smoke_pull_request_has_no_branches_filter():
    pr = _triggers(_load())["pull_request"]
    assert "branches" not in pr


def test_ci_smoke_pull_request_types():
    types = _triggers(_load())["pull_request"]["types"]
    assert set(types) == {"opened", "synchronize", "reopened", "edited"}


def test_ci_smoke_workflow_permissions():
    perms = _load()["permissions"]
    assert perms["contents"] == "read"
    assert perms["actions"] == "read"
    assert perms["checks"] == "write"