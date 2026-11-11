"""Guard: monkeypatched predictions-store stubs must accept keyword args."""

from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap

from internal.learning import predictions_store

REPO = pathlib.Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

_STORE_FUNCS = (
    "load_predictions",
    "save_predictions",
    "append_prediction",
)


def _accepts_arbitrary_kwargs(node: ast.AST) -> bool:
    """Require ``**kwargs`` (or ``**_kwargs``), not bare keyword-only params."""
    if isinstance(node, ast.Lambda):
        return bool(node.args.kwarg)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return bool(node.args.kwarg)
    return False


def _path_targets_store(path_str: str) -> bool:
    return "predictions_store" in path_str and any(
        path_str.endswith(fn) for fn in _STORE_FUNCS
    )


def _setattr_targets_store(call: ast.Call) -> tuple[bool, ast.AST | None]:
    """Return (is_store_target, stub_node). Handles 2- and 3-arg setattr forms."""
    if len(call.args) == 2:
        target = call.args[0]
        stub = call.args[1]
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            if _path_targets_store(target.value):
                return True, stub
        return False, None
    if len(call.args) >= 3:
        stub = call.args[2]
        if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            if _path_targets_store(call.args[0].value):
                return True, stub
        if isinstance(call.args[1], ast.Constant) and call.args[1].value in _STORE_FUNCS:
            return True, stub
    return False, None


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _direct_defs_in_scope(scope: ast.AST) -> dict[str, ast.AST]:
    """Function defs declared as direct statements in this scope (incl. async)."""
    body: list[ast.stmt]
    if isinstance(scope, ast.Module):
        body = scope.body
    elif isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body = scope.body
    else:
        return {}
    found: dict[str, ast.AST] = {}
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[stmt.name] = stmt
    return found


def _resolve_stub(
    tree: ast.Module, call_node: ast.Call, stub: ast.AST
) -> ast.AST | None:
    """Resolve stub to a callable AST node; ``None`` means unresolvable."""
    if isinstance(stub, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
        return stub
    if not isinstance(stub, ast.Name):
        return None
    parents = _parent_map(tree)
    current: ast.AST | None = call_node
    while current is not None:
        if isinstance(current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            local = _direct_defs_in_scope(current)
            if stub.id in local:
                return local[stub.id]
        current = parents.get(current)
    return None


def _scan_module(tree: ast.Module, rel: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "setattr"):
            continue
        targeted, stub = _setattr_targets_store(node)
        if not targeted or stub is None:
            continue
        resolved = _resolve_stub(tree, node, stub)
        if resolved is None:
            hits.append(
                (node.lineno, "stub name could not be resolved — unsafe skip")
            )
            continue
        if not _accepts_arbitrary_kwargs(resolved):
            hits.append((node.lineno, "stub must accept **kwargs (fail_closed/persist)"))
    return hits


def _violations_in_source(source: str, filename: str = "<snippet>") -> list[tuple[int, str]]:
    tree = ast.parse(textwrap.dedent(source), filename=filename)
    return _scan_module(tree, filename)


def test_load_predictions_exposes_keyword_only_fail_closed():
    sig = inspect.signature(predictions_store.load_predictions)
    assert "fail_closed" in sig.parameters
    assert sig.parameters["fail_closed"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["persist"].kind == inspect.Parameter.KEYWORD_ONLY


def test_guard_positive_two_arg_string_lambda_without_kwargs():
    bad = """
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    """
    hits = _violations_in_source(bad, "two_arg_string.py")
    assert hits, "expected 2-arg string setattr lambda violation"


def test_guard_positive_three_arg_name_reference_without_kwargs():
    bad = """
    def locked_load():
        return {}

    monkeypatch.setattr(predictions_store, "load_predictions", locked_load)
    """
    hits = _violations_in_source(bad, "name_ref.py")
    assert hits, "expected Name stub without **kwargs violation"


def test_guard_positive_nested_test_function_without_kwargs():
    bad = """
    def test_wrap(monkeypatch):
        def locked_load():
            return {}

        monkeypatch.setattr(predictions_store, "load_predictions", locked_load)
    """
    hits = _violations_in_source(bad, "nested_test.py")
    assert hits, "expected nested Name stub without **kwargs violation"


def test_guard_nested_compatible_stub_passes():
    good = """
    def test_wrap(monkeypatch):
        def locked_load(**kwargs):
            return {}

        monkeypatch.setattr(predictions_store, "load_predictions", locked_load)
    """
    hits = _violations_in_source(good, "nested_ok.py")
    assert not hits


def test_guard_positive_rejects_kwonly_underscore_without_var_keyword():
    bad = """
    def _load(*, persist=True, _fail_closed=False):
        return {}

    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions", _load
    )
    """
    hits = _violations_in_source(bad, "kwonly_underscore.py")
    assert hits, "keyword-only underscore params do not accept fail_closed"


def test_prediction_store_monkeypatch_stubs_accept_kwargs():
    violations: list[str] = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path.name == "test_predictions_store_patch_contract.py":
            continue
        rel = path.relative_to(REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for lineno, msg in _scan_module(tree, rel):
            violations.append(f"{rel}:{lineno} {msg}")
    assert not violations, "Incompatible stubs:\n" + "\n".join(violations)


def test_save_predictions_signature_locked_save_compatibility():
    """``locked_save(data)`` in loop-closure tests matches store API today."""
    sig = inspect.signature(predictions_store.save_predictions)
    params = list(sig.parameters.values())
    assert params[0].name == "data"
    assert all(
        p.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for p in params[1:]
    )
    by_name = {p.name: p for p in params}
    assert by_name["trigger"].default == "save_predictions"
    assert by_name["path"].default is None
