"""Structural guards so common agent footguns fail in CI, not in prod.

ponytail: ceiling is regex/AST scans; upgrade path is typed router registry
(see draft PR) once conditional server.py imports are retired.
"""

import ast
import importlib
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_PY = REPO_ROOT / "server.py"

ROUTER_FLAG_NAMES = (
    "_COUNCIL_ROUTES",
    "_LEARNING_ROUTES",
    "_SIMIVISION_ROUTES",
    "_RUGGERS_ROUTES",
    "_INDICATORS_ROUTES",
    "_ORACLE_ROUTES",
    "_ANALYTICS_ROUTES",
    "_HEALTH_ROUTES",
    "_INVESTIGATION_ROUTES",
    "_SHARE_ROUTES",
    "_COCKPIT_ROUTES",
    "_STORE_ROUTES",
    "_MINDMAP_GRAPH_ROUTES",
    "_SIGNALS_ROUTES",
    "_DEV_RADAR_ROUTES",
    "_CONVICTION_INDEX_ROUTES",
)

FORBIDDEN_IMPORTS = {"server_original", "flask", "gunicorn"}


def _python_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if parts[0] in {".venv", "venv", "node_modules"}:
            continue
        if ".venv" in parts:
            continue
        yield rel.as_posix(), path


def test_contract_entries_are_unique():
    from tests.test_endpoint_contract import CONTRACT

    seen = {}
    dupes = []
    for method, path, _ in CONTRACT:
        key = (method, path)
        if key in seen:
            dupes.append(key)
        seen[key] = True
    assert not dupes, f"duplicate CONTRACT entries: {dupes}"


def test_no_forbidden_runtime_imports_in_product_code():
    hits = []
    for rel, path in _python_files():
        if rel.startswith("tests/"):
            continue
        if rel == "server.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in FORBIDDEN_IMPORTS:
                        hits.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".", 1)[0] in FORBIDDEN_IMPORTS:
                    hits.append(f"{rel}:{node.lineno} from {node.module} import ...")
    assert not hits, "forbidden imports:\n" + "\n".join(hits)


def test_server_router_import_flags_are_true():
    """Conditional include_router blocks must not silently drop slices in CI."""
    server = importlib.import_module("server")
    bad = []
    for name in ROUTER_FLAG_NAMES:
        if not getattr(server, name, False):
            bad.append(name)
    assert not bad, (
        "router slice failed to import; fix the import instead of shipping "
        f"with flags false: {bad}"
    )


def test_server_has_no_duplicate_include_router_lines():
    text = SERVER_PY.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if "include_router(" in ln]
    dupes = sorted({ln for ln in lines if lines.count(ln) > 1})
    assert not dupes, f"duplicate include_router lines: {dupes}"


def test_agents_md_mentions_contract_guard():
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "test_endpoint_contract.py" in agents
    assert "single-foundation" in agents.lower() or "single foundation" in agents.lower()


def test_server_entrypoint_forbidden_imports():
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"), filename="server.py")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in FORBIDDEN_IMPORTS:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".", 1)[0] in FORBIDDEN_IMPORTS:
                hits.append(f"from {node.module}")
    assert not hits, f"forbidden imports in server.py: {hits}"


def test_mount_registry_loads_every_router():
    from internal.routing.mount_registry import MOUNTS, load_all

    assert len(MOUNTS) >= 10
    names = [name for name, _ in load_all()]
    assert len(names) == len(set(names))
