#!/usr/bin/env python3
"""Build r27-p4-v2 PASS fixture (full tests/ suite + shard matrix)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(__file__).resolve().parent / "build_r27_fixtures.py"
spec = importlib.util.spec_from_file_location("build_r27_fixtures", BUILD)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_r27_fixtures"] = mod
spec.loader.exec_module(mod)

SLUG = "p4-v2"
FIX = mod.FIX / "r27-p4-v2"
BASE_SHA = mod.BASE_SHA


def repo_for() -> dict:
    wf_head = (
        "name: ci-smoke\n"
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    strategy:\n"
        "      matrix:\n"
        "        shard-index: [0, 1, 2]\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: pip install pytest pytest-shard\n"
        "      - run: python -m pytest -q tests/ "
        "--shard-id=${{ matrix.shard-index }} --num-shards=3\n"
    )
    wf_base = (
        "name: ci-smoke\n"
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: pytest -q\n"
    )
    mod_src = (
        "from __future__ import annotations\n\n\n"
        "def suite_anchor(step: int) -> int:\n"
        "    \"\"\"Deterministic suite helper (not a tautology target).\"\"\"\n"
        "    return (step * 7 + 11) % 97\n"
    )
    tests = (
        "import pytest\n\n"
        "from internal.r27_suite_anchor import suite_anchor\n\n\n"
        "def test_anchor_baseline():\n"
        "    assert suite_anchor(0) == 11\n\n\n"
        "@pytest.mark.parametrize(\n"
        '    "step,expected",\n'
        "    [(1, 18), (2, 25), (3, 32), (4, 39), (5, 46), (6, 53), (7, 60), (8, 67), (9, 74)],\n"
        ")\n"
        "def test_anchor_steps(step, expected):\n"
        "    assert suite_anchor(step) == expected\n"
    )
    return {
        "files": {
            ".github/workflows/ci-smoke.yml": wf_head,
            "internal/r27_suite_anchor.py": mod_src,
            "tests/test_r27_suite_anchor.py": tests,
        },
        "baseFiles": {".github/workflows/ci-smoke.yml": wf_base},
    }


def main() -> None:
    repo = repo_for()
    diff = mod.build_diff(repo)
    diff_json = json.dumps(diff, indent=2, sort_keys=False) + "\n"
    diff_sha = mod.sha256_text(diff_json)
    head = "a27f000000000000000000000000000000000104"
    gate = mod.gate_doc(head)
    FIX.mkdir(parents=True, exist_ok=True)
    changed = sorted(set(repo["files"]) | set(repo.get("baseFiles", {})))
    changed = [
        p
        for p in changed
        if repo["files"].get(p, "") != repo.get("baseFiles", {}).get(p, "")
    ]
    meta = {
        "title": "ci: shard full test suite with matrix",
        "body": "Adds suite tests and shards the full tests/ tree via python -m pytest (same scope as base pytest -q, not a single smoke file).",
    }
    pr = {
        "number": 9631,
        "title": meta["title"],
        "body": meta["body"],
        "url": "https://github.com/cryptoreporthub/subnet-dashboard/pull/9631",
        "headSha": head,
        "baseSha": BASE_SHA,
        "draft": False,
        "files": changed,
    }
    oracle_doc = {
        "fixture": "r27-p4-v2",
        "slug": "p4-v2",
        "mechanism": "P4",
        "variant": "p4-v2",
        "baseSha": BASE_SHA,
        "diffSha256": diff_sha,
        "changedPaths": changed,
        "behavior": {"expectedVerdict": "PASS"},
        "labeling": {"note": "Replaces p4; Claude dual label on p4-v2 pending"},
        "pytest": {"summary": "10 passed", "passed": 10, "failed": 0, "skipped": 0, "failingTests": []},
    }
    (FIX / "pr.json").write_text(json.dumps(pr, indent=2) + "\n", encoding="utf-8")
    (FIX / "gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    (FIX / "repo.json").write_text(json.dumps(repo, indent=2) + "\n", encoding="utf-8")
    (FIX / "diff.json").write_text(diff_json, encoding="utf-8")
    (FIX / "oracle.json").write_text(json.dumps(oracle_doc, indent=2) + "\n", encoding="utf-8")
    mod.write_blind(
        "p4-v2",
        {"title": meta["title"], "body": meta["body"]},
        gate,
        diff,
        repo,
    )
    row = {
        "slug": "p4-v2",
        "fixture": "r27-p4-v2",
        "fixturePath": "exam-artifacts/r27/fixtures/r27-p4-v2",
        "oracle": "PASS",
        "sha256": {
            "diff": diff_sha,
            "oracle": mod.sha256_file(FIX / "oracle.json"),
            "repo": mod.sha256_file(FIX / "oracle.json"),
        },
    }
    row["sha256"]["repo"] = mod.sha256_file(FIX / "repo.json")

    manifest = json.loads((mod.R27 / "stage-c-manifest.json").read_text())
    new_fixtures = []
    for f in manifest["fixtures"]:
        if f["slug"] == "p4":
            new_fixtures.append(row)
        elif f["slug"] != "p4-v2":
            new_fixtures.append(f)
    manifest["fixtures"] = new_fixtures
    manifest["retired"]["p4"] = "r27-p4 narrowed smoke file + tautology; replaced by p4-v2 full tests/ shard"
    manifest.pop("p4Relabel", None)
    (mod.R27 / "stage-c-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote r27-p4-v2", diff_sha)


if __name__ == "__main__":
    main()
