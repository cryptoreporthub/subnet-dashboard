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


def _disallowed_tools(wf):
    args = shlex.split(_step(wf, "anthropics/claude-code-action")["with"]["claude_args"])
    assert "--disallowedTools" in args
    return args[args.index("--disallowedTools") + 1].split(",")


def _named_step(wf, name):
    steps = [s for s in wf["jobs"]["review"]["steps"] if s.get("name") == name]
    assert len(steps) == 1, f"expected one step named {name!r}, found {len(steps)}"
    return steps[0]


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
    # The allowlist is the security contract, so every entry is pinned, not a deny list.
    # Read, Grep and Glob run inside the CLI process, so each is scoped to the checkout
    # with `./**`. Local probe on CLI 2.1.332 (the version the pinned action installs):
    # unscoped, they read files outside the checkout, also through a symlink inside it;
    # scoped, those reads are denied. The CLI itself also refuses /proc and /dev paths.
    entries = _allowed_tools(_load())
    assert {entry.split("(", 1)[0] for entry in entries} == {
        "mcp__github_inline_comment__create_inline_comment",
        "Bash",
        "Read",
        "Grep",
        "Glob",
    }
    assert {entry for entry in entries if entry.startswith("Bash")} == {
        "Bash(gh pr comment:*)",
        "Bash(gh pr diff:*)",
        "Bash(gh pr view:*)",
    }
    assert {entry for entry in entries if entry.split("(", 1)[0] in {"Read", "Grep", "Glob"}} == {
        "Read(./**)",
        "Grep(./**)",
        "Glob(./**)",
    }


def test_file_tools_are_never_unscoped():
    # A bare `Read`, `Grep` or `Glob` would allow any path on the runner.
    for entry in _allowed_tools(_load()):
        assert entry not in {"Read", "Grep", "Glob", "Bash"}, entry
        assert not entry.startswith("Bash(*"), entry


def test_proc_is_denied_to_the_file_tools():
    # Belt and braces: `//proc/**` is an absolute path rule. A single-slash `/proc/**`
    # would mean "relative to the project root", and would not match /proc.
    assert set(_disallowed_tools(_load())) == {
        "Read(//proc/**)",
        "Grep(//proc/**)",
        "Glob(//proc/**)",
    }


def test_review_job_fails_when_nothing_was_posted():
    wf = _load()
    steps = wf["jobs"]["review"]["steps"]
    review_index = steps.index(_step(wf, "anthropics/claude-code-action"))
    check = _named_step(wf, "Fail if no review or summary was posted")
    # It runs after the review, on success only, so a green job means something was posted.
    assert steps.index(check) > review_index
    assert "if" not in check
    assert "continue-on-error" not in check
    script = check["run"]
    for endpoint in ("issues/${PR}/comments", "pulls/${PR}/reviews", "pulls/${PR}/comments"):
        assert endpoint in script
    assert 'select(.user.login == "github-actions[bot]"' in script
    assert "$since" in script
    assert "exit 1" in script
    # Start time is recorded by an earlier step and read through the step output.
    started = _named_step(wf, "Record job start")
    assert steps.index(started) < review_index
    assert check["env"]["SINCE"] == "${{ steps." + started["id"] + ".outputs.at }}"


def test_post_check_adds_no_permission_and_no_secret():
    wf = _load()
    check = _named_step(wf, "Fail if no review or summary was posted")
    assert set(check["env"]) == {"GH_TOKEN", "REPO", "PR", "SINCE"}
    assert check["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "secrets." not in str(check)
    assert wf["jobs"]["review"]["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_actions_run_the_reviewed_commit():
    # The job holds CLAUDE_CODE_OAUTH_TOKEN. A mutable tag would let an upstream
    # re-point run code with that secret, so each action is pinned to the commit reviewed.
    reviewed = {
        "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
        "anthropics/claude-code-action": "4411a9e9b0283becf4b924f7bce360fd7756c78c",
    }
    for prefix, sha in reviewed.items():
        assert _step(_load(), prefix)["uses"] == f"{prefix}@{sha}"


def test_mention_workflow_also_runs_the_reviewed_action_commit():
    mention = WORKFLOW.parent / "claude-mention.yml"
    wf = yaml.safe_load(mention.read_text())
    uses = [
        s["uses"]
        for job in wf["jobs"].values()
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("anthropics/claude-code-action")
    ]
    assert uses == ["anthropics/claude-code-action@4411a9e9b0283becf4b924f7bce360fd7756c78c"]


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
