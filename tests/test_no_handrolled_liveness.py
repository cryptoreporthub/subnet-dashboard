"""CI teeth: no hand-rolled liveness outside internal/liveness.py.

Fails if any SCHEDULER module under internal/ (other than the sanctioned
liveness module and files on the shrinking legacy allowlist) assigns the
hand-rolled liveness fields or bakes an "ok": True literal into a dict.

v2 design notes (after first CI run taught two lessons):
* Detection covers BOTH bare-name assigns (`_running = ...`) and
  attribute assigns (`self._running = ...`) -- v1's ast.walk missed
  attribute targets entirely because ast.Attribute stores the field name
  as .attr, not a Name node.
* Scoping is limited to scheduler-named modules (`*scheduler*.py`).
  A repo-wide scan produced false positives on every legitimate health
  endpoint returning {"ok": True}. Known limitation: non-scheduler-named
  background loops escape this net; tightening is tracked alongside the
  migration work rather than blocking it.
"""

import ast
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INTERNAL_ROOT = REPO_ROOT / "internal"
SANCTIONED = "internal/liveness.py"
STATE_PATH = REPO_ROOT / "tests" / "liveness_allowlist_state.json"
PREV_STATE_PATH = REPO_ROOT / "tests" / ".liveness_allowlist_prev.json"

FORBIDDEN_ASSIGNS = {"_running", "_last_run_ok", "_last_run_at"}


def _is_scheduler_module(rel):
    base = rel.rsplit("/", 1)[-1].lower()
    return rel.endswith(".py") and "scheduler" in base


def _load_allowlist():
    if not STATE_PATH.exists():
        return set()
    return set(json.loads(STATE_PATH.read_text()))


def _violations(rel, tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names = {tgt.id}
                elif isinstance(tgt, ast.Attribute):
                    names = {tgt.attr}
                else:
                    names = set()
                bad = sorted(names & FORBIDDEN_ASSIGNS)
                if bad:
                    found.append(
                        (rel, getattr(node, "lineno", 0), "assign:" + ",".join(bad))
                    )
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "ok"
                    and isinstance(v, ast.Constant)
                    and v.value is True
                ):
                    found.append(
                        (rel, getattr(node, "lineno", 0), 'dict-literal:"ok":True')
                    )
    return found


def test_no_new_handrolled_liveness():
    allowlist = _load_allowlist()
    violations = []
    for p in INTERNAL_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel == SANCTIONED:
            continue
        if not _is_scheduler_module(rel):
            continue
        if rel in allowlist:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        violations.extend(_violations(rel, tree))
    assert not violations, "hand-rolled liveness in scheduler module(s):\n" + "\n".join(
        "{}:{} {}".format(f, ln, kind) for f, ln, kind in violations
    )


def test_allowlist_monotonically_shrinks():
    allowlist = _load_allowlist()
    if PREV_STATE_PATH.exists():
        prev = set(json.loads(PREV_STATE_PATH.read_text()))
        added = allowlist - prev
        assert not added, "liveness allowlist re-added entries: {}".format(sorted(added))
    PREV_STATE_PATH.write_text(json.dumps(sorted(allowlist), indent=2))
