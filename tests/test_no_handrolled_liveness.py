"""CI teeth: no hand-rolled liveness outside internal/liveness.py.

Fails if any module under internal/ (other than the sanctioned liveness
module and files on the shrinking legacy allowlist) assigns the classic
hand-rolled liveness fields or bakes an "ok": True literal into a dict.

Rollout policy: allowlist-shrink. Each migration PR deletes its entry and
must pass the conformance fixture. Re-adding an allowlist entry fails
test_allowlist_monotonically_shrinks.
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


def _load_allowlist():
    if not STATE_PATH.exists():
        return set()
    return set(json.loads(STATE_PATH.read_text()))


def _violations(rel, tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                names = [
                    n.id for n in ast.walk(tgt) if isinstance(n, ast.Name)
                ]
                bad = [n for n in names if n in FORBIDDEN_ASSIGNS]
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
                    found.append((rel, getattr(node, "lineno", 0), 'dict-literal:"ok":True'))
    return found


def test_no_new_handrolled_liveness():
    allowlist = _load_allowlist()
    violations = []
    for p in INTERNAL_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel == SANCTIONED or rel.startswith("tests/"):
            continue
        if rel in allowlist:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        violations.extend(_violations(rel, tree))
    assert not violations, "hand-rolled liveness outside liveness.py:\n" + "\n".join(
        "{}:{} {}".format(f, ln, kind) for f, ln, kind in violations
    )


def test_allowlist_monotonically_shrinks():
    allowlist = _load_allowlist()
    if PREV_STATE_PATH.exists():
        prev = set(json.loads(PREV_STATE_PATH.read_text()))
        added = allowlist - prev
        assert not added, "liveness allowlist re-added entries: {}".format(
            sorted(added)
        )
    PREV_STATE_PATH.write_text(json.dumps(sorted(allowlist), indent=2))
