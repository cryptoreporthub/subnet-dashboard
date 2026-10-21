"""Learning state has one authority: graded outcomes, applied by an explicit allowlist of modules.

Unverified inputs (client feedback, message-intel patterns) must never write council,
signal, impact or judge weights. If this test fails, a new weight writer was added:
route the change through the resolver/estimator instead of extending ALLOWED_WRITERS.
"""

import ast
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

WRITER_CALLS = {
    "nudge_expert",
    "nudge_signal_weight",
    "nudge_impact_strength",
    "nudge_judge",
    "save_weights",
    "save_signal_weights",
    "save_judge_weights",
    "rebalance_council_weights",
    "repair_stale_contrarian_weights",
    # resolver internals that apply a grade to weights (also used by expired_recovery)
    "_stamp_and_nudge_expert",
    "_nudge_weights",
    "_nudge_signal_weights",
    "_nudge_impact_strength",
}

# Scenario memory is learning state too: scenario_outcome_adjustment tilts council scores from it.
SCENARIO_CALLS = {"add_scenario", "_record_scenario_outcome"}

# module -> reason it may write weights
ALLOWED_WRITERS = {
    "internal/council/resolver.py": "applies graded outcomes at resolve time",
    "internal/council/weights.py": "the weight store itself",
    "internal/judges/tracker.py": "judge nudges on graded outcomes",
    "internal/judges/weights.py": "the judge weight store itself",
    "internal/calibration/pipeline.py": "env-gated batch calibration with backup/rollback",
    "internal/learning/routes.py": "token-protected manual rebalance route",
    "internal/learning/expired_recovery.py": "re-grades expired rows against recovered prices via the resolver",
    "scripts/rebalance_expert_weights.py": "manual operator script",
}

ALLOWED_SCENARIO_WRITERS = {
    "internal/council/resolver.py": "records graded outcomes",
    "internal/learning/expired_recovery.py": "records outcomes for recovered rows",
    "internal/learning/prediction_loop.py": "records the scenario at pick creation",
    "internal/learning/routes.py": "token-protected POST /api/scenario-memory",
}

SKIP_DIRS = {"tests"}


def _tracked_python_files():
    """Scan what the repo ships (tracked files), not whatever is on disk: a checkout can hold
    worktrees, virtualenvs or copies of the code that are not part of it."""
    listing = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [REPO_ROOT / name for name in listing]


def _called_writers(tree, calls):
    """Names from ``calls`` that this module uses, by call or by reference.

    A reference counts as use, so ``w = nudge_expert; w()`` and passing a writer as a value are
    caught as well as ``from x import writer as alias`` and ``module.writer(...)``.
    """
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name in calls and item.asname:
                    aliases[item.asname] = item.name
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        else:
            continue
        name = aliases.get(name, name)
        if name in calls:
            found.add(name)
    return found


WEIGHT_STATE_KEYS = {
    "expert_weights",
    "council_weights",
    "signal_weights",
    "impact_strength",
    "judge_weights",
}

# Modules that name a weight key and use write_soul_map without setting a weight.
SOUL_MAP_KEY_NON_WRITERS = {
    "scripts/compact_soul_map.py": "lists expert_weights as a key that must survive compaction",
}


def _weight_keys_named(tree):
    """Weight-state keys a module names as a string, a keyword argument, or a subscript key."""
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            keys.add(node.value)
        elif isinstance(node, ast.keyword) and node.arg:
            keys.add(node.arg)
    return keys & WEIGHT_STATE_KEYS


def _soul_map_weight_key_modules():
    """Modules that name a weight-state key and reach the soul map through ``write_soul_map``.

    This is the persistence boundary: any such module can change stored weights, whatever
    function names it uses (a lambda or a local variable included).
    """
    found = {}
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except (SyntaxError, UnicodeDecodeError):
            continue
        keys = _weight_keys_named(tree)
        if keys and _called_writers(tree, {"write_soul_map"}):
            found[rel.as_posix()] = keys
    return found


def _writer_modules(calls=None):
    calls = WRITER_CALLS if calls is None else calls
    found = {}
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        except (SyntaxError, UnicodeDecodeError):
            continue
        names = _called_writers(tree, calls)
        if names:
            found[rel.as_posix()] = names
    return found


def test_guard_sees_reassigned_and_passed_writers():
    reassigned = ast.parse("from internal.council.weights import nudge_expert\nw = nudge_expert\nw('quant', True)\n")
    assert _called_writers(reassigned, WRITER_CALLS) == {"nudge_expert"}
    passed = ast.parse("import internal.council.weights as cw\nrun(cw.save_weights)\n")
    assert _called_writers(passed, WRITER_CALLS) == {"save_weights"}


def test_boundary_guard_sees_lambda_soul_map_write():
    tree = ast.parse(
        "from internal.store.soul_map_io import write_soul_map\n"
        "write_soul_map(lambda blob: blob.update(expert_weights={}))\n"
    )
    assert _called_writers(tree, {"write_soul_map"}) == {"write_soul_map"}
    assert _weight_keys_named(tree) == {"expert_weights"}


def test_guard_sees_aliased_writer_imports():
    aliased = ast.parse("from internal.council.weights import nudge_expert as nx\nnx('quant', True)\n")
    assert _called_writers(aliased, WRITER_CALLS) == {"nudge_expert"}
    module_alias = ast.parse("import internal.council.weights as w\nw.nudge_expert('quant', True)\n")
    assert _called_writers(module_alias, WRITER_CALLS) == {"nudge_expert"}
    unrelated = ast.parse("def nx():\n    pass\nnx()\n")
    assert _called_writers(unrelated, WRITER_CALLS) == set()


def test_only_allowlisted_modules_write_weights():
    unexpected = {m: sorted(c) for m, c in _writer_modules().items() if m not in ALLOWED_WRITERS}
    assert not unexpected, (
        "weight writers outside the allowlist (unverified input must not move weights): "
        f"{unexpected}"
    )


def test_only_allowlisted_modules_write_scenario_memory():
    found = _writer_modules(SCENARIO_CALLS)
    # scenario_memory.py defines add_scenario; calls inside it are internal.
    found.pop("internal/council/scenario_memory.py", None)
    unexpected = {m: sorted(c) for m, c in found.items() if m not in ALLOWED_SCENARIO_WRITERS}
    assert not unexpected, f"scenario-memory writers outside the allowlist: {unexpected}"


def test_allowlist_has_no_stale_entries():
    stale = sorted(set(ALLOWED_WRITERS) - set(_writer_modules()))
    assert not stale, f"allowlisted modules that no longer write weights: {stale}"
    stale = sorted(set(ALLOWED_SCENARIO_WRITERS) - set(_writer_modules(SCENARIO_CALLS)))
    assert not stale, f"allowlisted modules that no longer write scenario memory: {stale}"


def test_only_allowlisted_modules_write_weight_keys_through_the_soul_map():
    unexpected = {
        m: sorted(keys)
        for m, keys in _soul_map_weight_key_modules().items()
        if m not in ALLOWED_WRITERS and m not in SOUL_MAP_KEY_NON_WRITERS
    }
    assert not unexpected, (
        "modules naming a weight key and writing the soul map outside the allowlist "
        f"(a lambda or alias write evades the call-name scan): {unexpected}"
    )
    stale = sorted(set(SOUL_MAP_KEY_NON_WRITERS) - set(_soul_map_weight_key_modules()))
    assert not stale, f"non-writer exemptions that no longer match: {stale}"
