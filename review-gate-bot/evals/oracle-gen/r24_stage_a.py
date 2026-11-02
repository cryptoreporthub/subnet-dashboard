#!/usr/bin/env python3
"""Generate r24 Stage A fixtures (H2 on b9ccd6a7). No model calls."""
import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = subprocess.check_output(["git", "-C", HERE, "rev-parse", "--show-toplevel"], text=True).strip()
BOTDIR = os.path.join(REPO, "review-gate-bot")
OUT = os.path.join(BOTDIR, "evals", "fixtures")
BASE_SHA = "882980b817986fdcd2766fb18d46525b8e1955fd"


def patch(base: str, head: str) -> str:
    import difflib

    a, b = base.splitlines(keepends=True), head.splitlines(keepends=True)
    out = list(difflib.unified_diff(a, b, n=3, lineterm="\n"))[2:]
    body = "".join(l if l.endswith("\n") else l + "\n" for l in out)
    return body.rstrip("\n")


def sha_for(name: str) -> str:
    return hashlib.sha1(("evals-hard:" + name).encode()).hexdigest()


def dump(path: str, obj) -> None:
    with open(path, "w") as h:
        json.dump(obj, h, indent=2)
        h.write("\n")


def write(dirname, number, title, files, sha=None, gate=None, oracle=None):
    d = os.path.join(OUT, dirname)
    os.makedirs(d, exist_ok=True)
    head = sha or sha_for(dirname)
    dump(
        f"{d}/pr.json",
        {
            "number": number,
            "title": title,
            "url": f"https://github.com/cryptoreporthub/subnet-dashboard/pull/{number}",
            "headSha": head,
            "baseSha": BASE_SHA,
            "draft": False,
            "files": [f[0] for f in files],
        },
    )
    g = {
        "headSha": head,
        "mc": "missing",
        "cursor": "missing",
        "ditto": "missing",
        "replit": "missing",
        "suite": "missing",
        "replitTagged": False,
        "next": "review",
    }
    g.update(gate or {})
    dump(f"{d}/gate.json", g)
    dfiles = []
    repo = {}
    base_files = {}
    for path, base, newt in files:
        base_s = base or ""
        new_s = "" if newt is None else newt
        status = "added" if base is None else "modified"
        p = patch(base_s, new_s)
        add = sum(1 for l in p.split("\n") if l.startswith("+") and not l.startswith("+++"))
        dele = sum(1 for l in p.split("\n") if l.startswith("-") and not l.startswith("---"))
        dfiles.append({"path": path, "status": status, "additions": add, "deletions": dele, "patch": p})
        repo[path] = new_s
        if base is not None:
            base_files[path] = base_s
    dump(f"{d}/diff.json", {"totalFiles": len(dfiles), "files": dfiles, "truncated": False, "omittedPaths": []})
    dump(f"{d}/repo.json", {"files": repo, "baseFiles": base_files})
    pin = hashlib.sha256(json.dumps([[f["path"], f["patch"]] for f in dfiles], sort_keys=True).encode()).hexdigest()
    o = {"fixture": dirname, "baseSha": BASE_SHA, "diffSha256": pin, "changedPaths": [f["path"] for f in dfiles]}
    if oracle:
        o.update(oracle)
    dump(f"{d}/oracle.json", o)
    return head


W = write


def pytest_green(passed: int, skipped: int = 0, deselected: int = 0) -> dict:
    parts = [f"{passed} passed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if deselected:
        parts.append(f"{deselected} deselected")
    return {
        "summary": ", ".join(parts),
        "passed": passed,
        "failed": 0,
        "skipped": skipped,
        "deselected": deselected,
        "failingTests": [],
    }


def oracle_pass(note: str, passed: int = 56, **extra) -> dict:
    return {"pytest": pytest_green(passed), "behavior": {"expectedVerdict": "PASS", "note": note, **extra}}


def oracle_modify(note: str, passed: int = 56, **extra) -> dict:
    return {"pytest": pytest_green(passed), "behavior": {"expectedVerdict": "MODIFY", "note": note, **extra}}


LEGACY_MOD = '''"""Legacy subnet probe helpers (scheduled for removal with v2 census)."""
from __future__ import annotations


def probe_once(netuid: int) -> bool:
    return netuid >= 0
'''

LEGACY_TEST = '''from internal.legacy_subnet_probe import probe_once


def test_probe_accepts_non_negative_netuid():
    assert probe_once(5) is True
'''

WORKFLOW_BASE = """name: ci-smoke\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"""

body = "def test_moved_happy_path():\n    assert 2 + 2 == 4\n"

W(
    "hard-r24-removal-guarded-a",
    9401,
    "chore: remove legacy subnet probe shim",
    [
        ("internal/legacy_subnet_probe.py", LEGACY_MOD, None),
        ("tests/test_legacy_subnet_probe.py", LEGACY_TEST, None),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Production helper and its dedicated tests removed in the same diff; full suite stays green.",
        passed=55,
    ),
)

W(
    "hard-r24-removal-guarded-b",
    9402,
    "refactor: drop census ping helper and bulk universe checks",
    [
        (
            "internal/subnet_universe.py",
            "def _legacy_census_ping() -> int:\n    return 1\n",
            "",
        ),
        (
            "tests/test_subnet_universe.py",
            "def test_legacy_census_ping():\n    from internal.subnet_universe import _legacy_census_ping\n    assert _legacy_census_ping() == 1\n\n"
            "def test_bulk_placeholder_one():\n    assert True\n\n"
            "def test_bulk_placeholder_two():\n    assert True\n\n"
            "def test_bulk_placeholder_three():\n    assert True\n\n"
            "def test_bulk_placeholder_four():\n    assert True\n\n"
            "def test_bulk_placeholder_five():\n    assert True\n\n"
            "def test_bulk_placeholder_six():\n    assert True\n\n"
            "def test_bulk_placeholder_seven():\n    assert True\n",
            "",
        ),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Removes guarded production code and seven dependent tests; recorded testcase count falls below 90% of base while comparison stays green.",
        passed=49,
        baseTestcases=56,
        headTestcases=49,
    ),
)

W(
    "hard-r24-tests-moved-a",
    9403,
    "test: relocate subnet sanity checks file",
    [
        ("tests/test_subnet_sanity_checks.py", body, None),
        ("tests/test_subnet_sanity.py", None, body),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass("Tests renamed/moved; assertion bodies unchanged; count preserved.", passed=56),
)

W(
    "hard-r24-tests-moved-b",
    9404,
    "test: split sanity checks into package layout",
    [
        ("tests/test_subnet_sanity.py", body, None),
        ("tests/sanity/test_core.py", None, body),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass("Tests moved under tests/sanity/ with identical bodies.", passed=56),
)

shard_a = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard: [1, 2]
    steps:
      - run: pytest -q --shard-id=${{ matrix.shard }} --num-shards=2
"""

W(
    "hard-r24-ci-sharding-a",
    9405,
    "ci: shard pytest across two runners",
    [(".github/workflows/ci-smoke.yml", WORKFLOW_BASE, shard_a)],
    gate={"suite": "clean"},
    oracle=oracle_pass("Two-shard matrix visible in diff; union covers prior single job.", passed=56),
)

shard_b = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard: [unit, integration]
    steps:
      - run: pytest -q -m ${{ matrix.shard }}
"""

W(
    "hard-r24-ci-sharding-b",
    9406,
    "ci: parallelize unit and integration markers",
    [(".github/workflows/ci-smoke.yml", WORKFLOW_BASE, shard_b)],
    gate={"suite": "clean"},
    oracle=oracle_pass("Marker-based parallel jobs; combined coverage matches monolithic run.", passed=56),
)

flag_mod = "USE_LEGACY_UNIVERSE_PARSER = True\n"
flag_test = """import os


def test_legacy_parser_flag_default():
    assert os.environ.get("USE_LEGACY_UNIVERSE_PARSER", "0") in ("0", "false", "")
"""

W(
    "hard-r24-deprecated-flag-a",
    9407,
    "chore: remove legacy universe parser flag",
    [
        ("internal/subnet_universe_flags.py", flag_mod, None),
        ("tests/test_subnet_universe_flags.py", flag_test, None),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass("Flag constant and its tests removed together.", passed=55),
)

W(
    "hard-r24-deprecated-flag-b",
    9408,
    "chore: drop experimental refresh toggle",
    [
        ("config/experimental_refresh.toml", "enabled = true\n", None),
        (
            "tests/test_experimental_refresh_config.py",
            "def test_refresh_toggle_enabled():\n    assert True\n",
            None,
        ),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass("Experimental toggle config and tests removed in one diff.", passed=55),
)

W(
    "hard-r24-test-deleted-prod-kept",
    9409,
    "test: delete stale universe regression file",
    [
        (
            "tests/test_subnet_universe_stale_regression.py",
            "def test_stale_regression_placeholder():\n    from internal.subnet_universe import STALE_GRACE_SECONDS\n    assert STALE_GRACE_SECONDS > 0\n",
            None,
        ),
    ],
    gate={"suite": "clean"},
    oracle=oracle_modify(
        "Tests removed while production code they guarded remains; comparison can stay green.",
        passed=55,
    ),
)

W(
    "hard-r24-consolidation-drops-coverage",
    9410,
    "test: consolidate universe edge cases",
    [
        (
            "tests/test_subnet_universe.py",
            "def test_edge_a():\n    assert True\n\ndef test_edge_b():\n    assert True\n",
            "def test_edge_combined():\n    assert True\n",
        ),
    ],
    gate={"suite": "clean"},
    oracle=oracle_modify("Two cases merged into one; coverage narrows with green suite.", passed=55),
)

missing_shard = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard: [1]
    steps:
      - run: pytest -q --shard-id=1 --num-shards=2
"""

W(
    "hard-r24-sharding-missing-shard",
    9411,
    "ci: start pytest sharding rollout",
    [(".github/workflows/ci-smoke.yml", WORKFLOW_BASE, missing_shard)],
    gate={"suite": "clean"},
    oracle=oracle_modify("Matrix runs only shard 1 of 2; half of suite never executes.", passed=56),
)

print("wrote r24 Stage A fixtures under", OUT)
