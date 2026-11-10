"""Guard: monkeypatched predictions-store stubs must accept keyword args."""

from __future__ import annotations

import ast
import inspect
import pathlib

from internal.learning import predictions_store

REPO = pathlib.Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

_STORE_FUNCS = (
    "load_predictions",
    "save_predictions",
    "append_prediction",
)


def _stub_accepts_kwargs(node: ast.AST) -> bool:
    if isinstance(node, ast.Lambda):
        args = node.args
        return bool(args.kwarg) or bool(args.kwonlyargs and args.kwonlyargs[-1].arg.startswith("_"))
    if isinstance(node, ast.FunctionDef):
        return bool(node.args.kwarg) or any(
            a.arg.startswith("_") for a in node.args.kwonlyargs
        )
    return True


def _setattr_targets_store(call: ast.Call) -> bool:
    if len(call.args) < 3:
        return False
    path_str = None
    attr_name = None
    if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        path_str = call.args[0].value
    elif len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        attr_name = call.args[1].value
    if path_str and "predictions_store" in path_str:
        return any(path_str.endswith(fn) for fn in _STORE_FUNCS)
    if attr_name in _STORE_FUNCS:
        return True
    return False


def _scan_file(path: pathlib.Path) -> list[tuple[int, str]]:
    rel = path.relative_to(REPO).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "setattr"):
            continue
        if not _setattr_targets_store(node):
            continue
        stub = node.args[2]
        if isinstance(stub, (ast.Lambda, ast.FunctionDef)) and not _stub_accepts_kwargs(stub):
            hits.append((node.lineno, "stub must accept **kwargs (fail_closed/persist)"))
    return hits


def test_load_predictions_exposes_keyword_only_fail_closed():
    sig = inspect.signature(predictions_store.load_predictions)
    assert "fail_closed" in sig.parameters
    assert sig.parameters["fail_closed"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["persist"].kind == inspect.Parameter.KEYWORD_ONLY


def test_prediction_store_monkeypatch_stubs_accept_kwargs():
    violations: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == "test_predictions_store_patch_contract.py":
            continue
        for lineno, msg in _scan_file(path):
            violations.append(f"{path.name}:{lineno} {msg}")
    assert not violations, "Incompatible stubs:\n" + "\n".join(violations)
