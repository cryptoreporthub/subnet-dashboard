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
    if isinstance(node, ast.FunctionDef):
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


def _resolve_stub(tree: ast.Module, stub: ast.AST) -> ast.AST | None:
    if isinstance(stub, (ast.Lambda, ast.FunctionDef)):
        return stub
    if isinstance(stub, ast.Name):
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == stub.id:
                return node
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
        resolved = _resolve_stub(tree, stub)
        if resolved is None:
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
