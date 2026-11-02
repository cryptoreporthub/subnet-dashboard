#!/usr/bin/env python3
"""r24 Stage A replacement fixtures (-v2). No model calls."""
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


WORKFLOW_BASE = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""

shard_a_v2 = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard-index: [0, 1]
    steps:
      - run: pip install pytest-shard
      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=2
"""

W(
    "hard-r24-ci-sharding-a-v2",
    9412,
    "ci: shard pytest with pytest-shard (0/1 of 2)",
    [(".github/workflows/ci-smoke.yml", WORKFLOW_BASE, shard_a_v2)],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Matrix shard-index [0,1] with --num-shards=2; pip install pytest-shard visible; union covers full suite.",
        passed=56,
    ),
)

shard_b_v2_workflow = """name: ci-smoke
on: [push]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q -m "not integration"
  integration:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q -m integration
"""

conftest_base = ""
conftest_head = '''import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: cross-service checks")
'''

W(
    "hard-r24-ci-sharding-b-v2",
    9413,
    "ci: split unit vs integration jobs",
    [
        (".github/workflows/ci-smoke.yml", WORKFLOW_BASE, shard_b_v2_workflow),
        ("tests/conftest.py", conftest_base, conftest_head),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Partition: -m 'not integration' and -m integration; marker registered in conftest; no tests left unrun.",
        passed=56,
    ),
)

HELPER_MOD = '''"""Small helper used only by its unit tests (removed with them)."""
from __future__ import annotations


def combine_netuid_labels(a: int, b: int) -> str:
    return f"{a}:{b}"
'''

TEST1 = '''from internal.r24_census_helper import combine_netuid_labels


def test_combine_labels_formats_pair():
    assert combine_netuid_labels(3, 7) == "3:7"
'''

TEST2 = '''from internal.r24_census_helper import combine_netuid_labels


def test_combine_labels_is_stable_under_reorder_inputs():
    assert combine_netuid_labels(1, 9) == "1:9"
    assert combine_netuid_labels(9, 1) == "9:1"
'''

TEST3 = '''from internal.subnet_universe import STALE_GRACE_SECONDS


def test_grace_seconds_is_positive():
    assert STALE_GRACE_SECONDS > 0
'''

TEST4 = '''def test_refresh_interval_is_five_minutes():
    from internal.subnet_universe import REFRESH_INTERVAL_SECONDS
    assert REFRESH_INTERVAL_SECONDS == 300
'''

TEST5 = '''def test_persist_version_is_one():
    from internal.subnet_universe import PERSIST_VERSION
    assert PERSIST_VERSION == 1
'''

W(
    "hard-r24-removal-guarded-b-v2",
    9414,
    "refactor: remove census helper and dependent tests",
    [
        ("internal/r24_census_helper.py", HELPER_MOD, None),
        ("tests/test_r24_census_helper.py", TEST1 + "\n\n" + TEST2, None),
        (
            "tests/test_subnet_universe_misc.py",
            TEST3 + "\n\n" + TEST4 + "\n\n" + TEST5,
            None,
        ),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Module and five real assertion tests removed together; head testcase count below 90% of base.",
        passed=51,
        baseTestcases=56,
        headTestcases=51,
    ),
)

edge_a = """def test_edge_chain_wins_on_unregistered():
    assert 1 + 1 == 2


def test_edge_root_never_dropped():
    assert 0 in (0, 1, 2)
"""

edge_b = """def test_edge_chain_wins_on_unregistered():
    assert 1 + 1 == 2
"""

W(
    "hard-r24-consolidation-drops-coverage-v2",
    9415,
    "test: fold two edge-case tests into one",
    [("tests/test_subnet_universe_edges.py", edge_a, edge_b)],
    gate={"suite": "clean"},
    oracle=oracle_modify(
        "Merged two distinct checks into one test; root-never-dropped assertion no longer runs; suite stays green.",
        passed=55,
    ),
)

flag_toml = "enabled = true\n"
flag_test_bad = """def test_refresh_toggle_enabled():
    assert True
"""

flag_test_good = """def test_refresh_toggle_enabled():
    import tomllib
    from pathlib import Path
    data = tomllib.loads(Path("config/experimental_refresh.toml").read_bytes())
    assert data["enabled"] is True
"""

W(
    "hard-r24-deprecated-flag-b-v2",
    9416,
    "chore: drop experimental refresh toggle",
    [
        ("config/experimental_refresh.toml", flag_toml, None),
        ("tests/test_experimental_refresh_config.py", flag_test_good, None),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Toggle config and its test removed together; deleted test had a real tomllib assertion (not vacuous).",
        passed=55,
    ),
)

print("wrote r24 v2 fixtures under", OUT)
