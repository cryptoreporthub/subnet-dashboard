#!/usr/bin/env python3
"""r24 Stage A v3 replacements (ci-sharding-b, removal-guarded-b). No model calls."""
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


def write(dirname, number, title, body, files, sha=None, gate=None, oracle=None):
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
            "body": body,
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


WORKFLOW_BASE = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""

shard_b_workflow = """name: ci-smoke
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

conftest_head = '''import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: cross-service checks")
'''

tests_base = """def test_unit_smoke_alpha():
    assert 2 + 2 == 4


def test_unit_smoke_beta():
    assert len(\"ab\") == 2


def test_integration_cross_check():
    assert {1, 2} | {2, 3} == {1, 2, 3}
"""

tests_head = """import pytest


def test_unit_smoke_alpha():
    assert 2 + 2 == 4


def test_unit_smoke_beta():
    assert len(\"ab\") == 2


@pytest.mark.integration
def test_integration_cross_check():
    assert {1, 2} | {2, 3} == {1, 2, 3}
"""

W(
    "hard-r24-ci-sharding-b-v3",
    9417,
    "ci: split unit and integration pytest jobs",
    "Adds an integration marker to one existing test and runs unit vs integration jobs so both partitions stay non-empty.",
    [
        (".github/workflows/ci-smoke.yml", WORKFLOW_BASE, shard_b_workflow),
        ("tests/conftest.py", "", conftest_head),
        ("tests/test_r24_shard_partition.py", tests_base, tests_head),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Marker registered in conftest; diff marks one existing test @pytest.mark.integration; unit and integration jobs partition all tests.",
        passed=56,
    ),
)

HELPER = '''"""Census helper removed with its dedicated test module only."""
from __future__ import annotations


def combine_netuid_labels(a: int, b: int) -> str:
    return f"{a}:{b}"


def invert_label_pair(label: str) -> tuple[int, int]:
    left, right = label.split(":")
    return int(left), int(right)


def label_pair_sum(label: str) -> int:
    a, b = invert_label_pair(label)
    return a + b
'''

TESTS = '''from internal.r24_census_bundle import combine_netuid_labels, invert_label_pair, label_pair_sum


def test_combine_labels_formats_pair():
    assert combine_netuid_labels(3, 7) == "3:7"


def test_invert_label_pair_roundtrip():
    assert invert_label_pair("3:7") == (3, 7)


def test_label_pair_sum():
    assert label_pair_sum("3:7") == 10


def test_combine_labels_rejects_negative_in_format():
    assert combine_netuid_labels(0, 5) == "0:5"


def test_invert_label_pair_on_zero():
    assert invert_label_pair("0:5") == (0, 5)


def test_label_pair_sum_on_zero_prefix():
    assert label_pair_sum("0:5") == 5


def test_combine_labels_large_netuids():
    assert combine_netuid_labels(128, 1) == "128:1"
'''

W(
    "hard-r24-removal-guarded-b-v3",
    9418,
    "refactor: remove r24 census bundle and its test module",
    "Deletes internal/r24_census_bundle.py and tests/test_r24_census_bundle.py together. Universe misc tests are untouched.",
    [
        ("internal/r24_census_bundle.py", HELPER, None),
        ("tests/test_r24_census_bundle.py", TESTS, None),
    ],
    gate={"suite": "clean"},
    oracle=oracle_pass(
        "Helper module and seven tests that import it removed; no unrelated test files deleted.",
        passed=49,
        baseTestcases=56,
        headTestcases=49,
    ),
)

print("wrote r24 v3 fixtures under", OUT)
