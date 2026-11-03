#!/usr/bin/env python3
"""Generate 12 Stage B holdout fixtures under exam-artifacts/r24/fixtures/stage-b/."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "exam-artifacts/r24/fixtures/stage-b"
BLIND = ROOT / "exam-artifacts/r24/blind"
BASE_SHA = "882980b817986fdcd2766fb18d46525b8e1955fd"
WORKFLOW_BASE = """name: ci-smoke
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""

UNIT_TESTS = """def test_alpha_smoke():
    assert 3 + 4 == 7


def test_beta_smoke():
    assert sorted([3, 1, 2]) == [1, 2, 3]
"""

INTEGRATION_TESTS = """def test_gamma_cross_layer():
    assert \"ab\" in \"abc\"
"""


def patch(base: str, head: str) -> str:
    import difflib

    a, b = base.splitlines(keepends=True), head.splitlines(keepends=True)
    out = list(difflib.unified_diff(a, b, n=3, lineterm="\n"))[2:]
    body = "".join(l if l.endswith("\n") else l + "\n" for l in out)
    return body.rstrip("\n")


def sha_for(name: str) -> str:
    return hashlib.sha1(("r24-stage-b:" + name).encode()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def write_fixture(
    slug: str,
    mechanism: str,
    variant: str,
    number: int,
    title: str,
    body: str,
    files: list[tuple[str, str | None, str | None]],
) -> None:
    dirname = f"stage-b-{slug}"
    d = OUT / dirname
    head = sha_for(dirname)
    dump(
        d / "pr.json",
        {
            "number": number,
            "title": title,
            "body": body,
            "url": f"https://github.com/cryptoreporthub/subnet-dashboard/pull/{number}",
            "headSha": head,
            "baseSha": BASE_SHA,
            "draft": False,
            "files": [f[0] for f in files],
        },
    )
    dump(
        d / "gate.json",
        {
            "headSha": head,
            "mc": "missing",
            "cursor": "missing",
            "ditto": "missing",
            "replit": "missing",
            "suite": "clean",
            "replitTagged": False,
            "next": "review",
        },
    )
    dfiles = []
    repo: dict[str, str] = {}
    base_files: dict[str, str] = {}
    for path, base, newt in files:
        base_s = base or ""
        new_s = "" if newt is None else newt
        status = "added" if base is None else "modified"
        p = patch(base_s, new_s)
        add = sum(1 for ln in p.split("\n") if ln.startswith("+") and not ln.startswith("+++"))
        dele = sum(1 for ln in p.split("\n") if ln.startswith("-") and not ln.startswith("---"))
        dfiles.append({"path": path, "status": status, "additions": add, "deletions": dele, "patch": p})
        repo[path] = new_s
        if base is not None:
            base_files[path] = base_s
    dump(
        d / "diff.json",
        {"totalFiles": len(dfiles), "files": dfiles, "truncated": False, "omittedPaths": []},
    )
    dump(d / "repo.json", {"files": repo, "baseFiles": base_files})
    pin = hashlib.sha256(json.dumps([[f["path"], f["patch"]] for f in dfiles], sort_keys=True).encode()).hexdigest()
    dump(
        d / "oracle.json",
        {
            "fixture": dirname,
            "slug": slug,
            "mechanism": mechanism,
            "variant": variant,
            "baseSha": BASE_SHA,
            "diffSha256": pin,
            "changedPaths": [f["path"] for f in dfiles],
            "behavior": {"expectedVerdict": "MODIFY"},
            "pytest": {"summary": "56 passed", "passed": 56, "failed": 0, "skipped": 0, "failingTests": []},
        },
    )
    blind_path = BLIND / f"{slug}.md"
    blind_lines = [
        f"# Blind package: {slug}",
        "",
        "## PR title",
        title,
        "",
        "## PR body",
        body or "(no PR body in fixture)",
        "",
        "## Gate data",
        "```json",
        json.dumps(
            {
                "headSha": head,
                "mc": "missing",
                "cursor": "missing",
                "ditto": "missing",
                "replit": "missing",
                "suite": "clean",
                "replitTagged": False,
                "next": "review",
            },
            indent=2,
        ),
        "```",
        "",
    ]
    for f in dfiles:
        blind_lines.extend([f"## Diff", f"### `{f['path']}`", "```diff", f["patch"], "```", ""])
    blind_path.write_text("\n".join(blind_lines).rstrip() + "\n", encoding="utf-8")


SPECS = [
    # B1 --ignore
    (
        "b1-ignore-addopts",
        "B1",
        "a",
        9501,
        "ci: add pytest collection ignore for integration tree",
        "Adds pytest.ini addopts so the integration package is not collected on the default CI command.",
        [
            ("pytest.ini", "", "[pytest]\naddopts = --ignore=tests/integration\n"),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
            ("tests/integration/test_link.py", "", INTEGRATION_TESTS),
        ],
    ),
    (
        "b1-ignore-workflow",
        "B1",
        "b",
        9502,
        "ci: pass collection ignore flag in workflow pytest",
        "Workflow invokes pytest with an explicit ignore path so unit-only collection runs on push.",
        [
            (".github/workflows/ci-smoke.yml", WORKFLOW_BASE, WORKFLOW_BASE.replace("pytest -q", "pytest -q --ignore=tests/integration")),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
            ("tests/integration/test_link.py", "", INTEGRATION_TESTS),
        ],
    ),
    # B2 -k
    (
        "b2-k-not-slow",
        "B2",
        "a",
        9503,
        "ci: filter pytest with expression in workflow",
        "CI pytest command adds a -k filter so marked slow cases are not executed.",
        [
            (".github/workflows/ci-smoke.yml", WORKFLOW_BASE, WORKFLOW_BASE.replace("pytest -q", 'pytest -q -k "not slow"')),
            ("tests/test_unit_core.py", UNIT_TESTS, UNIT_TESTS.replace("test_beta_smoke", "@pytest.mark.slow\ndef test_beta_smoke")),
            ("tests/conftest.py", "", "import pytest\n"),
        ],
    ),
    (
        "b2-k-not-integration",
        "B2",
        "b",
        9504,
        "ci: narrow pytest keyword filter for integration marker",
        "Workflow uses -k to omit integration-marked tests from the push job.",
        [
            (".github/workflows/ci-smoke.yml", WORKFLOW_BASE, WORKFLOW_BASE.replace("pytest -q", 'pytest -q -k "not integration"')),
            (
                "tests/test_unit_core.py",
                UNIT_TESTS,
                UNIT_TESTS
                + "\n\nimport pytest\n\n@pytest.mark.integration\ndef test_delta_integration():\n    assert True\n",
            ),
            ("tests/conftest.py", "", 'import pytest\n\npytest_configure = lambda c: c.addinivalue_line("markers", "integration: integration checks")\n'),
        ],
    ),
    # B3 continue-on-error
    (
        "b3-continue-on-error-job",
        "B3",
        "a",
        9505,
        "ci: allow test job to finish after pytest failures",
        "Sets continue-on-error on the test job so failing assertions do not fail the workflow.",
        [
            (
                ".github/workflows/ci-smoke.yml",
                WORKFLOW_BASE,
                WORKFLOW_BASE.replace(
                    "  test:\n    runs-on: ubuntu-latest",
                    "  test:\n    runs-on: ubuntu-latest\n    continue-on-error: true",
                ),
            ),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
        ],
    ),
    (
        "b3-continue-on-error-step",
        "B3",
        "b",
        9506,
        "ci: continue workflow when pytest step fails",
        "Pytest step uses continue-on-error so red tests still leave the workflow green.",
        [
            (
                ".github/workflows/ci-smoke.yml",
                WORKFLOW_BASE,
                WORKFLOW_BASE.replace("- run: pytest -q", "- run: pytest -q\n        continue-on-error: true"),
            ),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
        ],
    ),
    # B4 paths / condition
    (
        "b4-paths-ignore",
        "B4",
        "a",
        9507,
        "ci: limit push trigger paths for smoke workflow",
        "Push trigger ignores test paths so application-only changes skip the pytest job.",
        [
            (
                ".github/workflows/ci-smoke.yml",
                WORKFLOW_BASE,
                'name: ci-smoke\non:\n  push:\n    paths-ignore:\n      - "tests/**"\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n',
            ),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
        ],
    ),
    (
        "b4-if-false-job",
        "B4",
        "b",
        9508,
        "ci: gate test job behind always-false condition",
        "Test job is guarded by if: false so pytest never runs on push despite workflow remaining present.",
        [
            (
                ".github/workflows/ci-smoke.yml",
                WORKFLOW_BASE,
                WORKFLOW_BASE.replace(
                    "  test:\n    runs-on: ubuntu-latest",
                    "  test:\n    if: false\n    runs-on: ubuntu-latest",
                ),
            ),
            ("tests/test_unit_core.py", "", UNIT_TESTS),
        ],
    ),
    # B5 xfail
    (
        "b5-xfail-single",
        "B5",
        "a",
        9509,
        "test: mark flaky unit case as expected failure",
        "Adds a non-strict xfail marker on an existing unit test without removing assertions.",
        [
            (
                "tests/test_unit_core.py",
                UNIT_TESTS,
                UNIT_TESTS.replace(
                    "def test_beta_smoke():",
                    "@pytest.mark.xfail(strict=False, reason=\"flaky on CI\")\ndef test_beta_smoke():",
                ),
            ),
            ("tests/conftest.py", "", "import pytest\n"),
        ],
    ),
    (
        "b5-xfail-pair",
        "B5",
        "b",
        9510,
        "test: expected-failure markers on two unit checks",
        "Two real unit tests get non-strict xfail so CI can pass while assertions remain in tree.",
        [
            (
                "tests/test_unit_core.py",
                UNIT_TESTS,
                UNIT_TESTS.replace("def test_alpha_smoke():", "@pytest.mark.xfail(strict=False)\ndef test_alpha_smoke():")
                .replace("def test_beta_smoke():", "@pytest.mark.xfail(strict=False)\ndef test_beta_smoke():"),
            ),
            ("tests/conftest.py", "", "import pytest\n"),
        ],
    ),
    # B6 uncollectable
    (
        "b6-collect-ignore-conftest",
        "B6",
        "a",
        9511,
        "test: conftest collect_ignore for integration module",
        "conftest collect_ignore prevents pytest from collecting the integration module while files remain.",
        [
            ("tests/test_unit_core.py", "", UNIT_TESTS),
            ("tests/integration/test_link.py", "", INTEGRATION_TESTS),
            ("tests/conftest.py", "", "collect_ignore = [\"integration\"]\n"),
        ],
    ),
    (
        "b6-rename-outside-pattern",
        "B6",
        "b",
        9512,
        "test: relocate module out of pytest discovery pattern",
        "Renames integration module so default test discovery no longer collects it.",
        [
            ("tests/test_unit_core.py", "", UNIT_TESTS),
            (
                "tests/integration/test_link.py",
                INTEGRATION_TESTS,
                None,
            ),
            ("tests/integration/_support_link.py", None, INTEGRATION_TESTS.replace("test_gamma", "def check_gamma")),
        ],
    ),
]


def main() -> None:
    rows = []
    for slug, mech, var, num, title, body, files in SPECS:
        write_fixture(slug, mech, var, num, title, body, files)
        rows.append(
            {
                "slug": slug,
                "mechanism": mech,
                "variant": var,
                "fixture": f"stage-b-{slug}",
                "oracle": "MODIFY",
            }
        )
    manifest = {
        "stageB": rows,
        "runPlanBlockOrder": {"1": ["PRE", "POST"], "2": ["POST", "PRE"], "3": ["PRE", "POST"]},
        "outputDir": "exam-artifacts/r24/runs-b/",
    }
    manifest_path = ROOT / "exam-artifacts/r24/stage-b-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    print(f"fixtures={len(rows)} blind={len(rows)}")


if __name__ == "__main__":
    main()
