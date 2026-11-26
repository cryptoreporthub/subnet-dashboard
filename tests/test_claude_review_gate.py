"""Regression test: when claude-review.yml runs, and what it can write.

The review job holds the repo secret, so it must run only for ready-for-review
PRs whose head branch lives in this repository, and it must never write contents.
"""

import fnmatch
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


def _prompt(wf):
    return _step(wf, "anthropics/claude-code-action")["with"]["prompt"]


def _bash_comment_allowed(command, wf=None):
    """Model of the CLI 2.1.332 Bash matcher for the comment rules: a command runs when an
    allow glob matches it and no deny glob does. `*` crosses spaces. Cross-checked against
    the real CLI in a local probe (see the PR body); it does not replace a live run."""
    wf = wf or _load()
    allow = [e[len("Bash("):-1] for e in _allowed_tools(wf) if e.startswith("Bash(gh pr comment")]
    deny = [e[len("Bash("):-1] for e in _disallowed_tools(wf) if e.startswith("Bash(gh pr comment")]
    return any(fnmatch.fnmatchcase(command, g) for g in allow) and not any(fnmatch.fnmatchcase(command, g) for g in deny)


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
    # `gh pr comment` is allowed only with `--body`. A bare `gh pr comment:*` would also
    # allow `--body-file`, which publishes any readable file as a public comment.
    assert {entry for entry in entries if entry.startswith("Bash")} == {
        "Bash(gh pr comment * --body *)",
        "Bash(gh pr diff:*)",
        "Bash(gh pr view:*)",
    }
    assert {entry for entry in entries if entry.split("(", 1)[0] in {"Read", "Grep", "Glob"}} == {
        "Read(./**)",
        "Grep(./**)",
        "Glob(./**)",
    }


def test_review_job_uses_only_user_setting_sources():
    # Ignore .claude settings and hooks a PR can add. The action writes its own
    # settings to ~/.claude/settings.json, which is the user source, so its MCP
    # setup still applies. allowed/disallowed tools are SDK options, not settings.
    args = shlex.split(_step(_load(), "anthropics/claude-code-action")["with"]["claude_args"])
    assert "--setting-sources" in args
    assert args[args.index("--setting-sources") + 1] == "user"


def test_review_job_uses_only_the_actions_own_mcp_servers():
    # The action passes its own servers (the inline-comment tool) with --mcp-config, which
    # --strict-mcp-config keeps. It drops every other source, such as a .mcp.json a PR adds.
    args = shlex.split(_step(_load(), "anthropics/claude-code-action")["with"]["claude_args"])
    assert "--strict-mcp-config" in args


def test_file_tools_are_never_unscoped():
    # A bare `Read`, `Grep` or `Glob` would allow any path on the runner.
    for entry in _allowed_tools(_load()):
        assert entry not in {"Read", "Grep", "Glob", "Bash"}, entry
        assert not entry.startswith("Bash(*"), entry


def test_proc_is_denied_to_the_file_tools():
    # Belt and braces: `//proc/**` is an absolute path rule. A single-slash `/proc/**`
    # would mean "relative to the project root", and would not match /proc.
    denied = set(_disallowed_tools(_load()))
    assert {"Read(//proc/**)", "Grep(//proc/**)", "Glob(//proc/**)"} <= denied


def test_comment_file_editor_and_edit_flags_are_denied():
    # `gh pr comment* --flag*` has no space after `comment`, so it also matches a flag
    # placed before the PR number. The old `gh pr comment * --flag*` form did not: with
    # `gh pr comment -F /f 1 --body hi` the allow rule matched and no deny did, so the
    # command ran (proved on CLI 2.1.332; see the PR body).
    assert {d for d in _disallowed_tools(_load()) if d.startswith("Bash")} == {
        "Bash(gh pr comment* --body-file*)",
        "Bash(gh pr comment* -F*)",
        "Bash(gh pr comment* --editor*)",
        "Bash(gh pr comment* -e)",
        "Bash(gh pr comment* -e *)",
        "Bash(gh pr comment* --edit-last*)",
        "Bash(gh pr comment* --delete-last*)",
        "Bash(gh pr comment* --create-if-none*)",
        "Bash(gh pr comment* --attach*)",
    }


def test_gh_pr_comment_runs_only_with_body():
    ok = [
        'gh pr comment 1 --body "hello world"',
        "gh pr comment 1 --body 'Review summary: all good'",
        "gh pr comment 1 --body \"$(cat <<'EOF'\n## Summary\n<!-- claude-review-run:1-1 -->\nEOF\n)\"",
        # Flag names in backticks inside the body are normal review text and stay allowed.
        "gh pr comment 1 --body \"$(cat <<'EOF'\nThe denies (`--body-file*`, `-F*`, `--editor*`) hold.\nEOF\n)\"",
        'gh pr comment 1 --body "non-Final pre-Fix re-use"',
    ]
    flags = [
        "--body-file /tmp/x",
        "--body-file=/tmp/x",
        "-F /tmp/x",
        "-F/tmp/x",
        "-F -",
        "--editor",
        "-e",
        "--edit-last",
        "--delete-last",
        "--create-if-none",
        "--attach /tmp/x",
    ]
    blocked = ["gh pr comment 1"]
    for flag in flags:
        # Before the PR number, after it, and after the body.
        blocked += [
            f"gh pr comment {flag} 1 --body hi",
            f"gh pr comment 1 {flag} --body hi",
            f"gh pr comment 1 --body hi {flag}",
            f"gh pr comment 1 -R o/r {flag}",
        ]
    for command in ok:
        assert _bash_comment_allowed(command), command
    for command in blocked:
        assert not _bash_comment_allowed(command), command


def test_each_new_deny_blocks_on_its_own():
    # Remove one deny at a time: its flag must then get through, so no deny is dead weight.
    wf = _load()
    allow = [e[len("Bash("):-1] for e in _allowed_tools(wf) if e.startswith("Bash(gh pr comment")]
    deny = [e[len("Bash("):-1] for e in _disallowed_tools(wf) if e.startswith("Bash(gh pr comment")]
    probes = {
        "gh pr comment* --body-file*": "gh pr comment --body-file /f 1 --body hi",
        "gh pr comment* -F*": "gh pr comment -F /f 1 --body hi",
        "gh pr comment* --editor*": "gh pr comment --editor 1 --body hi",
        "gh pr comment* -e": "gh pr comment 1 --body hi -e",
        "gh pr comment* -e *": "gh pr comment -e 1 --body hi",
        "gh pr comment* --edit-last*": "gh pr comment --edit-last 1 --body hi",
        "gh pr comment* --delete-last*": "gh pr comment --delete-last 1 --body hi",
        "gh pr comment* --create-if-none*": "gh pr comment --create-if-none 1 --body hi",
        "gh pr comment* --attach*": "gh pr comment --attach /f 1 --body hi",
    }
    assert set(probes) == set(deny)
    for glob, command in probes.items():
        others = [g for g in deny if g != glob]
        assert any(fnmatch.fnmatchcase(command, g) for g in allow), command
        assert not any(fnmatch.fnmatchcase(command, g) for g in others), (glob, command)
        assert fnmatch.fnmatchcase(command, glob), (glob, command)


def test_review_job_fails_when_no_marked_summary_was_posted():
    wf = _load()
    steps = wf["jobs"]["review"]["steps"]
    review_index = steps.index(_step(wf, "anthropics/claude-code-action"))
    check = _named_step(wf, "Fail if no review or summary was posted")
    # It runs after the review, on success only, so a green job means a marked summary exists.
    assert steps.index(check) > review_index
    assert "if" not in check
    assert "continue-on-error" not in check
    script = check["run"]
    # It looks in issue comments and review bodies for this run's marker, by the job token's bot.
    for endpoint in ("issues/${PR}/comments", "pulls/${PR}/reviews"):
        assert endpoint in script
    assert 'select(.user.login == "github-actions[bot]"' in script
    assert "contains($marker)" in script
    assert '--arg marker "$MARKER"' in script
    assert "exit 1" in script


def test_marker_is_unique_to_the_run_and_required_by_the_prompt():
    wf = _load()
    marker = "<!-- claude-review-run:${{ github.run_id }}-${{ github.run_attempt }} -->"
    # A re-run keeps the run id, so the attempt number is part of the marker.
    assert _named_step(wf, "Fail if no review or summary was posted")["env"]["MARKER"] == marker
    prompt = _prompt(wf)
    assert marker in prompt
    assert "first line of the summary" in prompt
    # The heredoc form is the one the CLI lets through when the text has newlines and `#`.
    assert "--body \"$(cat <<'EOF'" in prompt


def test_prompt_requires_untested_labels_and_keeps_the_marker():
    # Adversarial review lives in the prompt, not as runner skills. Keep the
    # posting contract: the marker and heredoc form must still be required.
    prompt = _prompt(_load())
    assert "UNTESTED" in prompt
    marker = "<!-- claude-review-run:${{ github.run_id }}-${{ github.run_attempt }} -->"
    assert marker in prompt
    assert "first line of the summary" in prompt
    assert "--body \"$(cat <<'EOF'" in prompt


def test_post_check_adds_no_permission_and_no_secret():
    wf = _load()
    check = _named_step(wf, "Fail if no review or summary was posted")
    assert set(check["env"]) == {"GH_TOKEN", "REPO", "PR", "MARKER"}
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


def test_sandbox_dependencies_are_installed_before_the_review():
    # The scrub makes the CLI require its Bash sandbox. Without bubblewrap and socat,
    # every Bash call fails and the review posts nothing (CLI 2.1.332, local probe).
    wf = _load()
    steps = wf["jobs"]["review"]["steps"]
    install = _named_step(wf, "Install Bash sandbox dependencies")
    assert steps.index(install) < steps.index(_step(wf, "anthropics/claude-code-action"))
    assert "bubblewrap socat" in install["run"]
    assert "apparmor_restrict_unprivileged_userns=0" in install["run"]
    # Fail loudly here rather than as a silent, empty review later.
    assert "continue-on-error" not in install
    assert "bwrap --unshare-all" in install["run"]
    assert "env" not in install


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
