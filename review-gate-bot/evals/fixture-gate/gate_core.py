"""Reusable checks for fixture gate + known-bad profiles."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TAUTOLOGY = re.compile(r"assert\s+True\b")
BARE_PYTEST = re.compile(r"^\s*-\s*run:\s*pytest\s", re.M)


def repo_files(repo_doc: dict) -> dict[str, str]:
    return repo_doc.get("files") or {}


def check_no_tautology_on_pass(repo_doc: dict, oracle: str) -> list[str]:
    if oracle != "PASS":
        return []
    errors: list[str] = []
    for path, content in repo_files(repo_doc).items():
        if not path.endswith(".py") or "test_" not in path:
            continue
        if TAUTOLOGY.search(content or ""):
            errors.append(f"tautology assert True in PASS fixture: {path}")
    return errors


def check_ci_pytest_invocation(repo_doc: dict) -> list[str]:
    errors: list[str] = []
    for path, content in repo_files(repo_doc).items():
        if ".github/workflows" not in path or not path.endswith((".yml", ".yaml")):
            continue
        if not content:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- run: pytest") or stripped.startswith("- run: pytest "):
                errors.append(f"bare pytest in workflow (need python -m pytest): {path}: {stripped}")
    return errors


def check_label_weight_assertion(repo_doc: dict) -> list[str]:
    """Wrong expected constant (729 vs measured 629 for legacy label)."""
    errors: list[str] = []
    prod = repo_files(repo_doc).get("internal/r25_label_weight.py") or ""
    if "label_weight" not in prod:
        return errors
    for path, content in repo_files(repo_doc).items():
        if not path.endswith(".py"):
            continue
        if re.search(r'label_weight\(["\']legacy["\']\)\s*==\s*729', content or ""):
            errors.append(f"wrong label_weight legacy expected 729 (should be 629): {path}")
    return errors


def check_r25_p6_behavior(repo_doc: dict) -> list[str]:
    """Production behavior changed vs base but tests emptied."""
    files = repo_files(repo_doc)
    base = repo_doc.get("baseFiles") or {}
    head_impl = files.get("internal/r25_feature_flags.py") or ""
    base_impl = base.get("internal/r25_feature_flags.py") or ""
    head_test = files.get("tests/test_r25_feature_flags.py") or ""
    base_test = base.get("tests/test_r25_feature_flags.py") or ""
    if not head_impl or not base_impl:
        return []
    if head_impl.strip() == base_impl.strip():
        return []
    if base_test.strip() and not head_test.strip():
        return ["r25-p6: production changed but head tests removed/empty vs base"]
    if "return True" in head_impl and "ENABLE_LEGACY_FOO" in base_impl and not head_test.strip():
        return ["r25-p6: refresh_enabled pinned True without tests"]
    return []


def check_shard_collects_nothing(repo_doc: dict, python: str) -> list[str]:
    files = repo_files(repo_doc)
    steps = []
    for path, content in files.items():
        if ".github/workflows" not in path:
            continue
        for line in (content or "").splitlines():
            if line.strip().startswith("- run:") and "pytest" in line:
                steps.append(line.strip().split("run:", 1)[1].strip())
    if not steps:
        return []
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for rel, content in files.items():
            if content == "":
                continue
            path = tdp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        env = {"PATH": str(Path(python).parent) + ":" + os.environ.get("PATH", "")}
        for raw in steps:
            cmd = raw.replace("${{ matrix.shard-index }}", "1").replace("${{matrix.shard-index}}", "1")
            if "pytest-shard" in cmd or "--shard-id" in cmd:
                proc = subprocess.run(
                    cmd,
                    cwd=str(tdp),
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                combined = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 5 or "no tests ran" in combined.lower():
                    errors.append(f"shard matrix index 1 collects nothing: exit={proc.returncode}")
    return errors


def validate_repo_doc(repo_doc: dict, *, python: str | None = None) -> list[str]:
    oracle = (repo_doc.get("oracle") or "MODIFY") if isinstance(repo_doc.get("oracle"), str) else "MODIFY"
    if isinstance(repo_doc.get("gate"), dict):
        oracle = repo_doc["gate"].get("oracle") or oracle
    errors: list[str] = []
    errors.extend(check_no_tautology_on_pass(repo_doc, oracle))
    errors.extend(check_ci_pytest_invocation(repo_doc))
    errors.extend(check_label_weight_assertion(repo_doc))
    errors.extend(check_r25_p6_behavior(repo_doc))
    if python:
        errors.extend(check_shard_collects_nothing(repo_doc, python))
    return errors


def git_show(repo_root: Path, rev: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def historical_rejection(
    repo_root: Path,
    rev: str,
    path: str,
    label: str,
    doc: dict,
    *,
    python: str | None = None,
) -> list[str]:
    """Rules that must fire on known-bad snapshots from git history (R0.2 acceptance)."""
    errors: list[str] = []
    errors.extend(validate_repo_doc(doc, python=python))
    files = repo_files(doc)
    if "consolidation-v1" in label or (
        rev.startswith("8ac92798") and "consolidation-drops-coverage/repo" in path
    ):
        head = files.get("tests/test_subnet_universe.py") or ""
        if "test_edge_combined" in head and TAUTOLOGY.search(head):
            errors.append("r24 consolidation-v1: merged edge tests collapsed to assert True")
    if "removal-guarded-b assert True" in label or (
        rev.startswith("8ac92798") and "removal-guarded-b/repo" in path and "v2" not in path
    ):
        head = files.get("tests/test_subnet_universe.py") or ""
        base = (doc.get("baseFiles") or {}).get("tests/test_subnet_universe.py") or ""
        if head.count("assert True") >= 3:
            errors.append("r24 removal-guarded-b v1: bulk placeholder tests are tautologies")
        elif not head.strip() and base.count("assert True") >= 3:
            errors.append("r24 removal-guarded-b v1: base tests are tautologies with empty head tests")
    return errors


def load_repo_json_at(repo_root: Path, rev: str, path: str) -> dict | None:
    raw = git_show(repo_root, rev, path)
    if not raw:
        return None
    return json.loads(raw)
