"""Regression test: when claude-review.yml runs, and what it can write.

The review job holds the repo secret, so it must run only for ready-for-review
PRs whose head branch lives in this repository, and it must never write contents.
"""

import shlex
from pathlib import Path

import yaml

from test_claude_mention_gate import evaluate

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "claude-review.yml"
REPO = "cryptoreporthub/subnet-dashboard"


def _load():
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(wf):
    # PyYAML reads the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


def _step(wf, uses_prefix):
    steps = [s for s in wf["jobs"]["review"]["steps"] if str(s.get("uses", "")).startswith(uses_prefix)]
    assert len(steps) == 1, f"expected one step using {uses_prefix}, found {len(steps)}"
    return steps[0]


def _allowed_tools(wf):
    args = shlex.split(_step(wf, "anthropics/claude-code-action")["with"]["claude_args"])
    assert "--allowedTools" in args
    return args[args.index("--allowedTools") + 1].split(",")


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


def test_allowed_tools_is_the_pinned_allowlist():
    # The allowlist is the security contract. Read, Grep and Glob reach the runner
    # filesystem, including /proc/self/environ, so every entry is pinned, not a deny list.
    entries = _allowed_tools(_load())
    assert {entry.split("(", 1)[0] for entry in entries} == {"mcp__github_inline_comment__create_inline_comment", "Bash"}
    assert {entry for entry in entries if entry.startswith("Bash")} == {
        "Bash(gh pr comment:*)",
        "Bash(gh pr diff:*)",
    }


def test_actions_run_the_reviewed_commit():
    # The job holds CLAUDE_CODE_OAUTH_TOKEN. A mutable tag would let an upstream
    # re-point run code with that secret, so each action is pinned to the commit reviewed.
    reviewed = {
        "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
        "anthropics/claude-code-action": "4411a9e9b0283becf4b924f7bce360fd7756c78c",
    }
    for prefix, sha in reviewed.items():
        assert _step(_load(), prefix)["uses"] == f"{prefix}@{sha}"


def test_review_job_opts_into_subprocess_env_scrub():
    # The action scrubs secrets from Bash children only when this is "1" (or when
    # allowed_non_write_users is set, which this job does not use). Source-derived:
    # the scrub itself runs in the Claude CLI, so a live run must confirm it.
    assert _load()["jobs"]["review"]["env"]["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"


def test_checkout_does_not_persist_the_workflow_token():
    # Persisted, the token sits in .git/config where a prompt-injected run can read it.
    assert _step(_load(), "actions/checkout")["with"]["persist-credentials"] is False


def test_only_cursor_bot_may_start_a_review():
    inputs = _step(_load(), "anthropics/claude-code-action")["with"]
    assert inputs["allowed_bots"] == "cursor[bot]"
