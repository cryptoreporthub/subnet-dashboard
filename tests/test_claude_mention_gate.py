"""Regression test: which jobs of claude-mention.yml run for a given comment.

Bot comments must never start a run. Only human OWNER, MEMBER or COLLABORATOR
comments that mention "@claude" start the write-capable claude-human job.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "claude-mention.yml"

_TOKEN = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>&&|\|\||==|!=|[()!,])|(?P<name>[A-Za-z_][A-Za-z0-9_.]*))"
)


def _tokenize(src):
    pos, out = 0, []
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise ValueError(f"cannot tokenize {src[pos:pos + 20]!r}")
        pos = m.end()
        if m.group("str") is not None:
            out.append(("str", m.group("str")[1:-1].replace("''", "'")))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        else:
            out.append(("name", m.group("name")))
    return out


def _truthy(v):
    return v not in (None, False, 0, "")


def _fold(v):
    return v.lower() if isinstance(v, str) else v


def _contains(a, b):
    if isinstance(a, list):
        return any(_fold(x) == _fold(b) for x in a)
    return isinstance(a, str) and isinstance(b, str) and b.lower() in a.lower()


# GitHub's string functions and == compare case-insensitively, so these do too.
_FUNCS = {
    "contains": _contains,
    "startsWith": lambda a, b: isinstance(a, str) and isinstance(b, str) and a.lower().startswith(b.lower()),
    "endsWith": lambda a, b: isinstance(a, str) and isinstance(b, str) and a.lower().endswith(b.lower()),
    "fromJSON": lambda s: json.loads(s),
}


class _Parser:
    def __init__(self, tokens, ctx):
        self.t, self.i, self.ctx = tokens, 0, ctx

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self, val=None):
        tok = self.t[self.i]
        if val is not None and tok[1] != val:
            raise ValueError(f"expected {val!r}, got {tok!r}")
        self.i += 1
        return tok

    def or_(self):
        left = self.and_()
        while self.peek() == ("op", "||"):
            self.eat()
            right = self.and_()
            left = left if _truthy(left) else right
        return left

    def and_(self):
        left = self.eq()
        while self.peek() == ("op", "&&"):
            self.eat()
            right = self.eq()
            left = right if _truthy(left) else left
        return left

    def eq(self):
        left = self.unary()
        while self.peek() in (("op", "=="), ("op", "!=")):
            op = self.eat()[1]
            right = self.unary()
            same = _fold(left) == _fold(right)
            left = same if op == "==" else not same
        return left

    def unary(self):
        if self.peek() == ("op", "!"):
            self.eat()
            return not _truthy(self.unary())
        return self.atom()

    def atom(self):
        kind, val = self.eat()
        if kind == "str":
            return val
        if (kind, val) == ("op", "("):
            v = self.or_()
            self.eat(")")
            return v
        if kind == "name":
            if self.peek() == ("op", "("):
                self.eat()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.or_())
                    while self.peek() == ("op", ","):
                        self.eat()
                        args.append(self.or_())
                self.eat(")")
                return _FUNCS[val](*args)
            if val == "null":
                return None
            cur = self.ctx
            for part in val.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            return cur
        raise ValueError(f"unexpected token {(kind, val)!r}")


def evaluate(expr, ctx):
    """Evaluate the subset this workflow uses: && || ! == != contains startsWith endsWith fromJSON,
    quoted strings and dotted lookups. Indexing and ternaries are not supported."""
    p = _Parser(_tokenize(expr), ctx)
    result = p.or_()
    assert p.i == len(p.t), "trailing tokens in expression"
    return _truthy(result)


def _payload(login, body, association="NONE", app=None):
    return {
        "github": {
            "event": {
                "comment": {
                    "body": body,
                    "user": {"login": login},
                    "author_association": association,
                    "performed_via_github_app": app,
                }
            }
        }
    }


def _runs(payload):
    wf = yaml.safe_load(WORKFLOW.read_text())
    runs = {}
    for name, job in wf["jobs"].items():
        if evaluate(str(job["if"]), payload):
            assert "permissions" in job, (
                f"{name} has no permissions block, so GitHub gives it the repo default (write)"
            )
            runs[name] = job["permissions"]
    return runs


def _writes_contents(perms):
    return perms.get("contents") == "write"


CASES = [
    ("a_bot_handoff", _payload("cursor[bot]", "@claude handoff-review please check the diff"), "none"),
    (
        "b_bot_quoted_mention",
        _payload("cursor[bot]", "Quoting the bot: > @claude handoff-review and also @claude review"),
        "none",
    ),
    ("c_bot_no_mention", _payload("cursor[bot]", "Auto-review found two issues in server.py"), "none"),
    ("d_bot_plain_mention", _payload("simibot[bot]", "@claude review please"), "none"),
    ("e_claude_bot", _payload("claude[bot]", "@claude handoff-review"), "none"),
    ("f_owner_mention", _payload("octocat", "@claude review", association="OWNER"), "human-write"),
    ("j_collaborator_mention", _payload("octocat", "@claude review", association="COLLABORATOR"), "human-write"),
    ("g_member_no_mention", _payload("octocat", "hello", association="MEMBER"), "none"),
    ("h_bot_member_assoc", _payload("cursor[bot]", "@claude review", association="MEMBER"), "none"),
    ("i_app_owner_assoc", _payload("some-app", "@claude review", association="OWNER", app={"slug": "x"}), "none"),
]


@pytest.mark.parametrize("payload,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_which_jobs_run(payload, expected):
    runs = _runs(payload)
    if expected == "none":
        assert runs == {}, f"jobs ran that must not: {sorted(runs)}"
    else:
        assert set(runs) == {"claude-human"}, f"jobs that ran: {sorted(runs)}"
        assert _writes_contents(runs["claude-human"]), f"human run lacks contents: write: {runs['claude-human']}"


def test_workflow_denies_default_permissions():
    wf = yaml.safe_load(WORKFLOW.read_text())
    assert wf.get("permissions") == {}, (
        "the workflow needs a top-level `permissions: {}`. Without it, any job that omits its own "
        "block gets the repo default token (write)."
    )

def _load():
    return yaml.safe_load(WORKFLOW.read_text())


def _human():
    return _load()["jobs"]["claude-human"]


def _step(uses_prefix=None, name=None):
    steps = _human()["steps"]
    if uses_prefix is not None:
        found = [s for s in steps if str(s.get("uses", "")).startswith(uses_prefix)]
        assert len(found) == 1, f"expected one step using {uses_prefix}, found {len(found)}"
        return found[0]
    found = [s for s in steps if s.get("name") == name]
    assert len(found) == 1, f"expected one step named {name!r}, found {len(found)}"
    return found[0]


def test_human_job_times_out_after_45_minutes():
    # A hung agent would otherwise hold contents: write until the runner default (6h).
    assert _human()["timeout-minutes"] == 45


def test_checkout_is_pinned_and_does_not_persist_the_workflow_token():
    # Same pin as the review job. The action replaces checkout credentials with its
    # own token before Claude runs, so git push still works without a persisted
    # checkout token sitting in .git/config.
    step = _step(uses_prefix="actions/checkout")
    assert step["uses"] == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    assert step["with"]["persist-credentials"] is False


def test_human_job_opts_into_subprocess_env_scrub():
    # claude_args is only `--model haiku`, so Claude can run Bash. The scrub without
    # the sandbox deps would stall those calls, as it did on the review job.
    assert _human()["env"]["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    args = _step(uses_prefix="anthropics/claude-code-action")["with"]["claude_args"]
    assert "--allowedTools" not in args


def test_sandbox_dependencies_are_installed_before_claude():
    # Mirror of the review job: install bubblewrap and socat, then fail loudly if
    # bwrap cannot start, before a secret-holding run begins.
    steps = _human()["steps"]
    install = _step(name="Install Bash sandbox dependencies")
    assert steps.index(install) < steps.index(_step(uses_prefix="anthropics/claude-code-action"))
    assert "bubblewrap socat" in install["run"]
    assert "apparmor_restrict_unprivileged_userns=0" in install["run"]
    assert "continue-on-error" not in install
    assert "bwrap --unshare-all" in install["run"]
