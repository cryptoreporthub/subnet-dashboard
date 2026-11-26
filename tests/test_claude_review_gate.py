"""Regression test: when claude-review.yml runs, and what it can write.

The review job holds the repo secret, so it must run only for ready-for-review
PRs whose head branch lives in this repository, and it must never write contents.
"""

from pathlib import Path

import pytest
import yaml

from test_claude_mention_gate import evaluate

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "claude-review.yml"
REPO = "cryptoreporthub/subnet-dashboard"


def _load():
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(wf):
    # PyYAML reads the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


def _ctx(action, draft=False, head_repo=REPO):
    return {
        "false": False,
        "true": True,
        "github": {
            "repository": REPO,
            "event": {
                "action": action,
                "pull_request": {"number": 7, "draft": draft, "head": {"repo": {"full_name": head_repo}}},
            },
        },
    }


def _jobs_that_run(ctx):
    return sorted(name for name, job in _load()["jobs"].items() if evaluate(str(job["if"]), ctx))


def test_draft_pr_is_skipped():
    assert _jobs_that_run(_ctx("synchronize", draft=True)) == []


def test_fork_pr_is_skipped():
    assert _jobs_that_run(_ctx("synchronize", head_repo="someone/subnet-dashboard")) == []


def test_same_repo_synchronize_runs():
    assert len(_jobs_that_run(_ctx("synchronize"))) == 1


def test_same_repo_ready_for_review_runs():
    assert len(_jobs_that_run(_ctx("ready_for_review"))) == 1


def test_trigger_types_are_exactly_the_three_review_moments():
    triggers = _triggers(_load())
    assert list(triggers) == ["pull_request"]
    assert sorted(triggers["pull_request"]["types"]) == ["opened", "ready_for_review", "synchronize"]


def test_no_job_can_write_contents():
    for name, job in _load()["jobs"].items():
        assert "permissions" in job, f"{name} has no permissions block, so it gets the repo default (write)"
        assert job["permissions"].get("contents") != "write", name


def test_top_level_permissions_are_empty():
    assert _load()["permissions"] == {}


def test_pull_request_target_is_not_used_anywhere():
    assert "pull_request_target" not in WORKFLOW.read_text()


def test_only_cursor_bot_may_start_a_review():
    wf = _load()
    inputs = wf["jobs"]["review"]["steps"][1]["with"]
    assert inputs["allowed_bots"] == "cursor[bot]"
