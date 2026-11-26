"""Regression test: which jobs of claude-mention.yml run for a given comment.

A bot comment that merely quotes "@claude" must not start a write-capable run.
Bots may start a run only with the "@claude handoff-review" phrase, and that
run must not have contents: write.
"""

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
    "fromJSON": lambda s: __import__("json").loads(s),
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
    top_perms = wf.get("permissions") or {}
    runs = {}
    for name, job in wf["jobs"].items():
        if evaluate(str(job["if"]), payload):
            runs[name] = job.get("permissions", top_perms)
    return runs


def _writes_contents(perms):
    return perms.get("contents") == "write"


CASES = [
    ("a_bot_handoff", _payload("cursor[bot]", "@claude handoff-review please check the diff"), "bot-readonly"),
    (
        "b_bot_quoted_mention",
        _payload("cursor[bot]", "Quoting the bot: > @claude handoff-review and also @claude review"),
        "none",
    ),
    ("c_bot_no_mention", _payload("cursor[bot]", "Auto-review found two issues in server.py"), "none"),
    ("d_bot_plain_mention", _payload("simibot[bot]", "@claude review please"), "none"),
    ("e_claude_bot", _payload("claude[bot]", "@claude handoff-review"), "none"),
    ("f_owner_mention", _payload("octocat", "@claude review", association="OWNER"), "human-write"),
    ("g_member_no_mention", _payload("octocat", "hello", association="MEMBER"), "none"),
]


@pytest.mark.parametrize("payload,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_which_jobs_run(payload, expected):
    runs = _runs(payload)
    if expected == "none":
        assert runs == {}, f"jobs ran that must not: {sorted(runs)}"
    elif expected == "bot-readonly":
        assert set(runs) == {"claude-bot"}, f"jobs that ran: {sorted(runs)}"
        assert not _writes_contents(runs["claude-bot"]), f"bot run has contents: write: {runs['claude-bot']}"
    else:
        assert set(runs) == {"claude-human"}, f"jobs that ran: {sorted(runs)}"
        assert _writes_contents(runs["claude-human"]), f"human run lacks contents: write: {runs['claude-human']}"


def test_bot_job_uses_job_scoped_token():
    wf = yaml.safe_load(WORKFLOW.read_text())
    step = next(s for s in wf["jobs"]["claude-bot"]["steps"] if s.get("name") == "Run Claude")
    assert step["with"].get("github_token") == "${{ github.token }}", (
        "claude-bot must pass github_token: ${{ github.token }}. Without this input the action "
        "mints a GitHub App token whose scope the job's permissions block does not bound."
    )
