import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_only_predictions_store_writes_the_ledger():
    violations = []
    for directory in ("internal", "scripts"):
        for path in (ROOT / directory).rglob("*.py"):
            if path.relative_to(ROOT).as_posix() == "internal/learning/predictions_store.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = function.id if isinstance(function, ast.Name) else (
                    function.attr if isinstance(function, ast.Attribute) else ""
                )
                forbidden = name in {"save_predictions", "_write_predictions_unlocked"}
                if name in {"safe_write_json", "_save_json"} and node.args:
                    target = ast.unparse(node.args[0]).lower()
                    forbidden = "prediction" in target or target == "resolved_path"
                if forbidden:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
    assert not violations, "\n".join(violations)
