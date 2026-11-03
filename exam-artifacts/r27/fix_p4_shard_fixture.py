#!/usr/bin/env python3
"""Build r27-p4 PASS shard fixture (tests + python -m pytest --shard-id)."""
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

SLUG = "p4"
FIX = mod.FIX / "r27-p4"
BLIND = mod.R27 / "blind"
BASE_SHA = mod.BASE_SHA


def repo_for_p4() -> dict:
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
        "      - run: python -m pytest -q tests/test_r27_shard_smoke.py "
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
    tests = (
        "import pytest\n\n\n"
        "@pytest.mark.parametrize(\"n\", list(range(9)))\n"
        "def test_shard_slot(n):\n"
        "    assert n * 2 == n + n\n"
    )
    return {
        "files": {
            ".github/workflows/ci-smoke.yml": wf_head,
            "tests/test_r27_shard_smoke.py": tests,
        },
        "baseFiles": {".github/workflows/ci-smoke.yml": wf_base},
    }


def main() -> None:
    repo = repo_for_p4()
    diff = mod.build_diff(repo)
    diff_json = json.dumps(diff, indent=2, sort_keys=False) + "\n"
    diff_sha = mod.sha256_text(diff_json)
    head = "a27f000000000000000000000000000000000004"
    gate = mod.gate_doc(head)
    FIX.mkdir(parents=True, exist_ok=True)
    changed = sorted(set(repo["files"]) | set(repo.get("baseFiles", {})))
    changed = [
        p
        for p in changed
        if repo["files"].get(p, "") != repo.get("baseFiles", {}).get(p, "")
    ]
    meta = {
        "title": "ci: add three-way pytest shard matrix with tests",
        "body": "Adds shard smoke tests and a 0-based matrix job using python -m pytest with pytest-shard.",
    }
    pr = {
        "number": 9624,
        "title": meta["title"],
        "body": meta["body"],
        "url": "https://github.com/cryptoreporthub/subnet-dashboard/pull/9624",
        "headSha": head,
        "baseSha": BASE_SHA,
        "draft": False,
        "files": changed,
    }
    oracle_doc = {
        "fixture": "r27-p4",
        "slug": "p4",
        "mechanism": "P4",
        "variant": "p4",
        "baseSha": BASE_SHA,
        "diffSha256": diff_sha,
        "changedPaths": changed,
        "behavior": {"expectedVerdict": "PASS"},
        "labeling": {"note": "r27-P4-FAIL fix: 9 cases / 3 shards; Claude re-label required"},
        "pytest": {"summary": "1 passed", "passed": 1, "failed": 0, "skipped": 0, "failingTests": []},
    }
    (FIX / "pr.json").write_text(json.dumps(pr, indent=2) + "\n", encoding="utf-8")
    (FIX / "gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    (FIX / "repo.json").write_text(json.dumps(repo, indent=2) + "\n", encoding="utf-8")
    (FIX / "diff.json").write_text(diff_json, encoding="utf-8")
    (FIX / "oracle.json").write_text(json.dumps(oracle_doc, indent=2) + "\n", encoding="utf-8")
    mod.write_blind(
        "p4",
        {"title": meta["title"], "body": meta["body"]},
        gate,
        diff,
        repo,
    )
    row = {
        "slug": "p4",
        "fixture": "r27-p4",
        "fixturePath": "exam-artifacts/r27/fixtures/r27-p4",
        "oracle": "PASS",
        "sha256": {
            "diff": diff_sha,
            "oracle": mod.sha256_file(FIX / "oracle.json"),
            "repo": mod.sha256_file(FIX / "repo.json"),
        },
    }
    manifest = json.loads((mod.R27 / "stage-c-manifest.json").read_text())
    for i, f in enumerate(manifest["fixtures"]):
        if f["slug"] == "p4":
            manifest["fixtures"][i] = row
            break
    manifest.setdefault("p4Relabel", "r27-GATE-DEFECT: p4 diff changed; Claude re-label both labelers")
    (mod.R27 / "stage-c-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote r27-p4", diff_sha)


if __name__ == "__main__":
    main()
