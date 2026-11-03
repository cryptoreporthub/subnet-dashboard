#!/usr/bin/env python3
"""Generate exam-artifacts/r25 fixtures, blind packs, and stage-c-manifest."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R25 = ROOT / "exam-artifacts/r25"
FIX = R25 / "fixtures"
BLIND = R25 / "blind"

BASE_SHA = "882980b817986fdcd2766fb18d46525b8e1955fd"

SLUGS = [
    "p1a",
    "p1b",
    "p2",
    "p3",
    "p4",
    "p5",
    "p6",
    "p7",
    "m1a",
    "m1b",
    "m1c",
    "m2a",
    "m2b",
    "m3a",
    "m3b",
    "m4a",
    "m4b",
    "m5a",
    "m5b",
    "m6",
]

HEAD_SHAS = [
    "a25f000000000000000000000000000000000001",
    "a25f000000000000000000000000000000000002",
    "a25f000000000000000000000000000000000003",
    "a25f000000000000000000000000000000000004",
    "a25f000000000000000000000000000000000005",
    "a25f000000000000000000000000000000000006",
    "a25f000000000000000000000000000000000007",
    "a25f000000000000000000000000000000000008",
    "a25f000000000000000000000000000000000009",
    "a25f00000000000000000000000000000000000a",
    "a25f00000000000000000000000000000000000b",
    "a25f00000000000000000000000000000000000c",
    "a25f00000000000000000000000000000000000d",
    "a25f00000000000000000000000000000000000e",
    "a25f00000000000000000000000000000000000f",
    "a25f000000000000000000000000000000000010",
    "a25f000000000000000000000000000000000011",
    "a25f000000000000000000000000000000000012",
    "a25f000000000000000000000000000000000013",
    "a25f000000000000000000000000000000000014",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def make_patch(old: str, new: str) -> tuple[str, int, int]:
    """Return (patch_body, additions, deletions) GitHub-style hunks only."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    if old == new:
        return "", 0, 0

    import difflib

    udiff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm="",
            n=3,
        )
    )
    hunks: list[str] = []
    adds = dels = 0
    for line in udiff:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
        if line.startswith("@@"):
            hunks.append(line)
        elif line.startswith(("+", "-", " ")):
            hunks.append(line)
    patch = "\n".join(hunks)
    if patch:
        patch += "\n"
    return patch, adds, dels


def build_diff(repo: dict) -> dict:
    files_map = repo.get("files") or {}
    base_map = repo.get("baseFiles") or {}
    all_paths = sorted(set(files_map) | set(base_map))
    entries = []
    for path in all_paths:
        old = base_map.get(path, "")
        new = files_map.get(path, "")
        if old == new:
            continue
        patch, adds, dels = make_patch(old, new)
        if old and not new:
            status = "removed"
        elif not old and new:
            status = "added"
        else:
            status = "modified"
        entries.append(
            {
                "path": path,
                "status": status,
                "additions": adds,
                "deletions": dels,
                "patch": patch,
            }
        )
    doc = {
        "totalFiles": len(entries),
        "files": entries,
        "truncated": False,
        "omittedPaths": [],
    }
    return doc


def gate_doc(head_sha: str) -> dict:
    return {
        "headSha": head_sha,
        "mc": "missing",
        "cursor": "missing",
        "ditto": "missing",
        "replit": "missing",
        "suite": "clean",
        "replitTagged": False,
        "next": "review",
    }


def mechanism_for(slug: str) -> tuple[str, str, str]:
    if slug.startswith("p"):
        return slug[0].upper() + slug[1], slug, "PASS"
    if slug.startswith("m"):
        return "M" + slug[1:3].rstrip("abc"), slug, "MODIFY"
    raise ValueError(slug)


def fixture_meta(slug: str, idx: int) -> dict:
    mech, variant, oracle = mechanism_for(slug)
    pr_num = 9601 + idx
    head = HEAD_SHAS[idx]
    titles = {
        "p1a": "chore: drop unused census index helper",
        "p1b": "refactor: remove quota stub module",
        "p2": "test: relocate layout checks package",
        "p3": "test: table-drive pair sum cases",
        "p4": "ci: add three-way pytest shard matrix",
        "p5": "test: add audit hook coverage job",
        "p6": "chore: remove legacy refresh flag",
        "p7": "test: move split validation to dedicated module",
        "m1a": "test: drop stale regression file",
        "m1b": "test: trim unused edge case",
        "m1c": "test: simplify hook smoke check",
        "m2a": "test: mark intermittent layout case xfail",
        "m2b": "test: skip module on unsupported runtime",
        "m3a": "test: ignore integration glob in conftest",
        "m3b": "test: narrow default pytest discovery paths",
        "m4a": "ci: limit pull_request workflow paths",
        "m4b": "ci: gate unit job on event type",
        "m5a": "ci: run single shard in three-shard layout",
        "m5b": "ci: adjust declared shard matrix",
        "m6": "test: reduce parametrized hook cases",
    }
    bodies = {
        "p1a": "Removes an internal helper and its dedicated tests that no longer ship in production builds.",
        "p1b": "Deletes the quota stub package together with the tests that only exercised that stub.",
        "p2": "Renames the layout test module without changing assertion text.",
        "p3": "Collapses separate pair-sum tests into one parametrized test with the same inputs.",
        "p4": "Adds a complete 0-based shard matrix matching num-shards.",
        "p5": "Introduces audit hook tests and a workflow job that runs them.",
        "p6": "Removes a deprecated boolean flag and the test that locked its default.",
        "p7": "Deletes an obsolete split test while adding the replacement case elsewhere.",
        "m1a": "Removes a regression test module; service code is unchanged.",
        "m1b": "Drops one test function from an existing module.",
        "m1c": "Leaves the test name but removes substantive assertions.",
        "m2a": "Applies a non-strict xfail to one existing test.",
        "m2b": "Adds a module-level skip for environments without the hook runtime.",
        "m3a": "Configures collect_ignore_glob for integration-style files.",
        "m3b": "Restricts pytest testpaths to a subset of directories.",
        "m4a": "Adds paths-ignore entries on pull_request events.",
        "m4b": "Skips the unit test job for pull_request events via job if.",
        "m5a": "Matrix executes one shard while declaring three total shards.",
        "m5b": "Matrix omits a shard index still implied by num-shards.",
        "m6": "Removes several parametrized cases; production helper unchanged.",
    }
    return {
        "slug": slug,
        "mechanism": mech if len(mech) <= 2 else mech[:2],
        "variant": variant,
        "oracle": oracle,
        "pr_num": pr_num,
        "head": head,
        "title": titles[slug],
        "body": bodies[slug],
    }


def repo_for(slug: str) -> dict:
    """Return {files, baseFiles} for each slug."""
    if slug == "p1a":
        mod = (
            '"""Unused census index (removed with v3 pipeline)."""\n'
            "from __future__ import annotations\n\n\n"
            "def index_netuid(netuid: int) -> int:\n"
            "    return netuid\n"
        )
        tst = (
            "from internal.r25_stale_index import index_netuid\n\n\n"
            "def test_index_non_negative():\n"
            "    assert index_netuid(3) == 3\n\n\n"
            "def test_index_zero():\n"
            "    assert index_netuid(0) == 0\n"
        )
        return {
            "files": {"internal/r25_stale_index.py": "", "tests/test_r25_stale_index.py": ""},
            "baseFiles": {
                "internal/r25_stale_index.py": mod,
                "tests/test_r25_stale_index.py": tst,
            },
        }
    if slug == "p1b":
        mod = (
            '"""Quota stub used only in fixture builds."""\n'
            "from __future__ import annotations\n\n\n"
            "def quota_headroom(limit: int, used: int) -> int:\n"
            "    return limit - used\n"
        )
        tst = (
            "from internal.r25_quota_stub import quota_headroom\n\n\n"
            "def test_headroom_positive():\n"
            "    assert quota_headroom(10, 4) == 6\n\n\n"
            "def test_headroom_zero_used():\n"
            "    assert quota_headroom(5, 0) == 5\n"
        )
        return {
            "files": {"internal/r25_quota_stub.py": "", "tests/test_r25_quota_stub.py": ""},
            "baseFiles": {
                "internal/r25_quota_stub.py": mod,
                "tests/test_r25_quota_stub.py": tst,
            },
        }
    if slug == "p2":
        body = (
            "def test_layout_columns_align():\n"
            "    assert len([1, 2, 3]) == 3\n\n\n"
            "def test_layout_rows_align():\n"
            "    assert sum([1, 1]) == 2\n"
        )
        return {
            "files": {
                "tests/test_r25_layout_a.py": "",
                "tests/layout/test_r25_layout_a.py": body,
            },
            "baseFiles": {"tests/test_r25_layout_a.py": body},
        }
    if slug == "p3":
        base = (
            "def test_pair_sum_two_and_three():\n"
            "    assert 2 + 3 == 5\n\n\n"
            "def test_pair_sum_four_and_one():\n"
            "    assert 4 + 1 == 5\n\n\n"
            "def test_pair_sum_zero_and_nine():\n"
            "    assert 0 + 9 == 9\n"
        )
        head = (
            "import pytest\n\n\n"
            "@pytest.mark.parametrize(\n"
            '    "left,right,expected",\n'
            "    [(2, 3, 5), (4, 1, 5), (0, 9, 9)],\n"
            ")\n"
            "def test_pair_sum(left, right, expected):\n"
            "    assert left + right == expected\n"
        )
        return {
            "files": {"tests/test_r25_pairs.py": head},
            "baseFiles": {"tests/test_r25_pairs.py": base},
        }
    if slug == "p4":
        wf = (
            "name: ci-smoke\n"
            "on: [push]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    strategy:\n"
            "      matrix:\n"
            "        shard-index: [0, 1, 2]\n"
            "    steps:\n"
            "      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=3\n"
        )
        return {
            "files": {".github/workflows/ci-smoke.yml": wf},
            "baseFiles": {
                ".github/workflows/ci-smoke.yml": (
                    "name: ci-smoke\non: [push]\njobs:\n  test:\n"
                    "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"
                )
            },
        }
    if slug == "p5":
        wf = (
            "name: ci-audit\n"
            "on: [push]\n"
            "jobs:\n"
            "  audit:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: pytest -q tests/test_r25_audit_hook.py\n"
        )
        tst = (
            "from internal.r25_audit_hook import emit_audit_tick\n\n\n"
            "def test_emit_audit_tick_increments():\n"
            "    assert emit_audit_tick(1) == 2\n"
        )
        mod = (
            "from __future__ import annotations\n\n\n"
            "def emit_audit_tick(value: int) -> int:\n"
            "    return value + 1\n"
        )
        return {
            "files": {
                ".github/workflows/ci-audit.yml": wf,
                "internal/r25_audit_hook.py": mod,
                "tests/test_r25_audit_hook.py": tst,
            },
            "baseFiles": {},
        }
    if slug == "p6":
        mod_base = (
            "from __future__ import annotations\n\n"
            "ENABLE_LEGACY_FOO = True\n\n\n"
            "def refresh_enabled() -> bool:\n"
            "    return not ENABLE_LEGACY_FOO\n"
        )
        mod_head = (
            "from __future__ import annotations\n\n\n"
            "def refresh_enabled() -> bool:\n"
            "    return True\n"
        )
        tst = (
            "from internal.r25_feature_flags import ENABLE_LEGACY_FOO\n\n\n"
            "def test_legacy_foo_default():\n"
            "    assert ENABLE_LEGACY_FOO is True\n"
        )
        return {
            "files": {
                "internal/r25_feature_flags.py": mod_head,
                "tests/test_r25_feature_flags.py": "",
            },
            "baseFiles": {
                "internal/r25_feature_flags.py": mod_base,
                "tests/test_r25_feature_flags.py": tst,
            },
        }
    if slug == "p7":
        old_t = (
            "def test_split_checksum_legacy():\n"
            "    assert hash('legacy') == hash('legacy')\n"
        )
        new_t = (
            "def test_split_checksum_current():\n"
            "    assert hash('current') == hash('current')\n"
        )
        return {
            "files": {
                "tests/test_r25_split_old.py": "",
                "tests/test_r25_split_new.py": new_t,
            },
            "baseFiles": {"tests/test_r25_split_old.py": old_t},
        }
    if slug == "m1a":
        svc = (
            "from __future__ import annotations\n\n\n"
            "def hook_value() -> int:\n"
            "    return 42\n"
        )
        tst = (
            "from internal.r25_m1a_service import hook_value\n\n\n"
            "def test_hook_value_stable():\n"
            "    assert hook_value() == 42\n"
        )
        return {
            "files": {
                "internal/r25_m1a_service.py": svc,
                "tests/test_r25_m1a_hook.py": "",
            },
            "baseFiles": {
                "internal/r25_m1a_service.py": svc,
                "tests/test_r25_m1a_hook.py": tst,
            },
        }
    if slug == "m1b":
        svc = (
            "from __future__ import annotations\n\n\n"
            "def edge_total(values: list[int]) -> int:\n"
            "    return sum(values)\n"
        )
        base_t = (
            "from internal.r25_m1b_service import edge_total\n\n\n"
            "def test_edge_total_simple():\n"
            "    assert edge_total([1, 2]) == 3\n\n\n"
            "def test_edge_total_empty():\n"
            "    assert edge_total([]) == 0\n"
        )
        head_t = (
            "from internal.r25_m1b_service import edge_total\n\n\n"
            "def test_edge_total_simple():\n"
            "    assert edge_total([1, 2]) == 3\n"
        )
        return {
            "files": {
                "internal/r25_m1b_service.py": svc,
                "tests/test_r25_m1b_edges.py": head_t,
            },
            "baseFiles": {
                "internal/r25_m1b_service.py": svc,
                "tests/test_r25_m1b_edges.py": base_t,
            },
        }
    if slug == "m1c":
        svc = (
            "from __future__ import annotations\n\n\n"
            "def smoke_token() -> str:\n"
            "    return \"ok\"\n"
        )
        base_t = (
            "from internal.r25_m1c_service import smoke_token\n\n\n"
            "def test_smoke_token():\n"
            "    assert smoke_token() == \"ok\"\n"
        )
        head_t = (
            "from internal.r25_m1c_service import smoke_token\n\n\n"
            "def test_smoke_token():\n"
            "    smoke_token()\n"
        )
        return {
            "files": {
                "internal/r25_m1c_service.py": svc,
                "tests/test_r25_m1c_smoke.py": head_t,
            },
            "baseFiles": {
                "internal/r25_m1c_service.py": svc,
                "tests/test_r25_m1c_smoke.py": base_t,
            },
        }
    if slug == "m2a":
        base_t = (
            "def test_alpha_layout():\n"
            "    assert 1 + 2 == 3\n\n\n"
            "def test_beta_layout():\n"
            "    assert sorted([3, 2, 1]) == [1, 2, 3]\n"
        )
        head_t = (
            "import pytest\n\n\n"
            "def test_alpha_layout():\n"
            "    assert 1 + 2 == 3\n\n\n"
            "@pytest.mark.xfail(strict=False, reason=\"order sensitive on CI\")\n"
            "def test_beta_layout():\n"
            "    assert sorted([3, 2, 1]) == [1, 2, 3]\n"
        )
        return {
            "files": {"tests/test_r25_m2a_layout.py": head_t},
            "baseFiles": {"tests/test_r25_m2a_layout.py": base_t},
        }
    if slug == "m2b":
        head_t = (
            "import pytest\n\n"
            "pytest.skip(\"hook runtime unavailable in this image\", allow_module_level=True)\n\n\n"
            "def test_hook_probe():\n"
            "    assert 2 + 2 == 4\n"
        )
        return {
            "files": {"tests/test_r25_m2b_hook.py": head_t},
            "baseFiles": {
                "tests/test_r25_m2b_hook.py": (
                    "def test_hook_probe():\n    assert 2 + 2 == 4\n"
                )
            },
        }
    if slug == "m3a":
        unit = (
            "def test_unit_only():\n"
            "    assert \"x\" in \"xy\"\n"
        )
        integ = (
            "def test_integration_only():\n"
            "    assert len(\"ab\") == 2\n"
        )
        conf = 'collect_ignore_glob = ["*_integration.py"]\n'
        return {
            "files": {
                "tests/test_r25_m3a_unit.py": unit,
                "tests/test_r25_m3a_integration.py": integ,
                "tests/conftest.py": conf,
            },
            "baseFiles": {
                "tests/test_r25_m3a_unit.py": unit,
                "tests/test_r25_m3a_integration.py": integ,
                "tests/conftest.py": "",
            },
        }
    if slug == "m3b":
        ini_head = "[pytest]\ntestpaths = tests/unit\n"
        ini_base = "[pytest]\ntestpaths = tests\n"
        unit = "def test_narrow_path():\n    assert 4 - 1 == 3\n"
        other = "def test_wide_path():\n    assert 2 * 3 == 6\n"
        return {
            "files": {
                "pytest.ini": ini_head,
                "tests/unit/test_r25_m3b_narrow.py": unit,
                "tests/test_r25_m3b_wide.py": other,
            },
            "baseFiles": {
                "pytest.ini": ini_base,
                "tests/unit/test_r25_m3b_narrow.py": unit,
                "tests/test_r25_m3b_wide.py": other,
            },
        }
    if slug == "m4a":
        wf_head = (
            "name: ci-smoke\n"
            "on:\n"
            "  pull_request:\n"
            "    paths-ignore:\n"
            "      - \"tests/**\"\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: pytest -q\n"
        )
        wf_base = (
            "name: ci-smoke\n"
            "on: [pull_request]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: pytest -q\n"
        )
        tst = "def test_m4a_smoke():\n    assert 5 + 5 == 10\n"
        return {
            "files": {
                ".github/workflows/ci-smoke.yml": wf_head,
                "tests/test_r25_m4a_smoke.py": tst,
            },
            "baseFiles": {
                ".github/workflows/ci-smoke.yml": wf_base,
                "tests/test_r25_m4a_smoke.py": "",
            },
        }
    if slug == "m4b":
        wf_head = (
            "name: ci-smoke\n"
            "on: [pull_request, push]\n"
            "jobs:\n"
            "  test:\n"
            "    if: github.event_name != 'pull_request'\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: pytest -q\n"
        )
        wf_base = (
            "name: ci-smoke\n"
            "on: [pull_request, push]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: pytest -q\n"
        )
        tst = "def test_m4b_smoke():\n    assert 6 + 6 == 12\n"
        return {
            "files": {
                ".github/workflows/ci-smoke.yml": wf_head,
                "tests/test_r25_m4b_smoke.py": tst,
            },
            "baseFiles": {
                ".github/workflows/ci-smoke.yml": wf_base,
                "tests/test_r25_m4b_smoke.py": "",
            },
        }
    if slug == "m5a":
        wf = (
            "name: ci-smoke\n"
            "on: [push]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    strategy:\n"
            "      matrix:\n"
            "        shard-index: [1]\n"
            "    steps:\n"
            "      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=3\n"
        )
        return {
            "files": {".github/workflows/ci-smoke.yml": wf},
            "baseFiles": {
                ".github/workflows/ci-smoke.yml": (
                    "name: ci-smoke\non: [push]\njobs:\n  test:\n"
                    "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"
                )
            },
        }
    if slug == "m5b":
        wf = (
            "name: ci-smoke\n"
            "on: [push]\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    strategy:\n"
            "      matrix:\n"
            "        shard-index: [0, 1]\n"
            "    steps:\n"
            "      - run: pytest -q --shard-id=${{ matrix.shard-index }} --num-shards=3\n"
        )
        return {
            "files": {".github/workflows/ci-smoke.yml": wf},
            "baseFiles": {
                ".github/workflows/ci-smoke.yml": (
                    "name: ci-smoke\non: [push]\njobs:\n  test:\n"
                    "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"
                )
            },
        }
    if slug == "m6":
        svc = (
            "from __future__ import annotations\n\n\n"
            "def scale_hook(value: int, factor: int) -> int:\n"
            "    return value * factor\n"
        )
        base_t = (
            "import pytest\n\n"
            "from internal.r25_m6_service import scale_hook\n\n\n"
            "@pytest.mark.parametrize(\n"
            '    "value,factor,expected",\n'
            "    [(2, 3, 6), (0, 5, 0), (4, 4, 16), (-1, 2, -2)],\n"
            ")\n"
            "def test_scale_hook(value, factor, expected):\n"
            "    assert scale_hook(value, factor) == expected\n"
        )
        head_t = (
            "import pytest\n\n"
            "from internal.r25_m6_service import scale_hook\n\n\n"
            "@pytest.mark.parametrize(\n"
            '    "value,factor,expected",\n'
            "    [(2, 3, 6), (0, 5, 0)],\n"
            ")\n"
            "def test_scale_hook(value, factor, expected):\n"
            "    assert scale_hook(value, factor) == expected\n"
        )
        return {
            "files": {
                "internal/r25_m6_service.py": svc,
                "tests/test_r25_m6_scale.py": head_t,
            },
            "baseFiles": {
                "internal/r25_m6_service.py": svc,
                "tests/test_r25_m6_scale.py": base_t,
            },
        }
    raise KeyError(slug)


def pytest_block(slug: str, oracle: str) -> dict:
    passed = 52 if oracle == "PASS" else 54
    if slug in ("p1a", "p1b"):
        passed = 50
    return {
        "summary": f"{passed} passed",
        "passed": passed,
        "failed": 0,
        "skipped": 0,
        "failingTests": [],
    }


def write_blind(slug: str, meta: dict, gate: dict, diff: dict, repo: dict) -> None:
    lines = [
        f"# Blind package: {slug}",
        "",
        "## PR title",
        meta["title"],
        "",
        "## PR body",
        meta["body"],
        "",
        "## Gate data",
        "```json",
        json.dumps(gate, indent=2),
        "```",
        "",
    ]
    for entry in diff["files"]:
        lines.extend(
            [
                "## Diff",
                f"### `{entry['path']}`",
                "```diff",
                entry["patch"].rstrip("\n"),
                "```",
                "",
            ]
        )
    lines.append("## Repo files (head, read-only context)")
    lines.append("")
    for path in sorted((repo.get("files") or {}).keys()):
        content = repo["files"][path]
        if content == "":
            lines.append(f"### `{path}`")
            lines.append("_(absent at head)_")
            lines.append("")
            continue
        lang = "python" if path.endswith(".py") else "yaml" if path.endswith((".yml", ".yaml")) else "ini" if path.endswith(".ini") else ""
        lines.append(f"### `{path}`")
        lines.append(f"```{lang}".rstrip())
        lines.append(content.rstrip("\n"))
        lines.append("```")
        lines.append("")
    out = BLIND / f"{slug}.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    BLIND.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for idx, slug in enumerate(SLUGS):
        meta = fixture_meta(slug, idx)
        repo = repo_for(slug)
        diff = build_diff(repo)
        diff_json = json.dumps(diff, indent=2, sort_keys=False) + "\n"
        diff_sha = sha256_text(diff_json)
        head = meta["head"]
        gate = gate_doc(head)
        fixture_name = f"r25-{slug}"
        fdir = FIX / fixture_name
        fdir.mkdir(parents=True, exist_ok=True)
        changed = sorted(
            set(repo.get("files", {})) | set(repo.get("baseFiles", {}))
        )
        changed = [p for p in changed if repo.get("files", {}).get(p, "") != repo.get("baseFiles", {}).get(p, "")]
        pr = {
            "number": meta["pr_num"],
            "title": meta["title"],
            "body": meta["body"],
            "url": f"https://github.com/cryptoreporthub/subnet-dashboard/pull/{meta['pr_num']}",
            "headSha": head,
            "baseSha": BASE_SHA,
            "draft": False,
            "files": changed,
        }
        mech = meta["mechanism"]
        if slug.startswith("p"):
            mech_label = f"P{slug[1:]}" if len(slug) > 2 else f"P{slug[1]}"
        else:
            mech_label = f"M{slug[1]}"
        oracle_doc = {
            "fixture": fixture_name,
            "slug": slug,
            "mechanism": mech_label.rstrip("abc") if mech_label.startswith("M") else mech_label.upper(),
            "variant": slug,
            "baseSha": BASE_SHA,
            "diffSha256": diff_sha,
            "changedPaths": changed,
            "behavior": {"expectedVerdict": meta["oracle"]},
            "pytest": pytest_block(slug, meta["oracle"]),
        }
        # normalize mechanism field
        if slug.startswith("p"):
            oracle_doc["mechanism"] = "P" + slug[1]
        else:
            oracle_doc["mechanism"] = "M" + slug[1]

        (fdir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n", encoding="utf-8")
        (fdir / "gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
        (fdir / "repo.json").write_text(json.dumps(repo, indent=2) + "\n", encoding="utf-8")
        (fdir / "diff.json").write_text(diff_json, encoding="utf-8")
        (fdir / "oracle.json").write_text(json.dumps(oracle_doc, indent=2) + "\n", encoding="utf-8")
        write_blind(slug, meta, gate, diff, repo)
        manifest_rows.append(
            {
                "slug": slug,
                "fixture": fixture_name,
                "fixturePath": f"exam-artifacts/r25/fixtures/{fixture_name}",
                "oracle": meta["oracle"],
                "sha256": {
                    "diff": diff_sha,
                    "oracle": sha256_file(fdir / "oracle.json"),
                    "repo": sha256_file(fdir / "repo.json"),
                },
            }
        )
    manifest = {
        "stage": "C",
        "baseSha": BASE_SHA,
        "fixtures": manifest_rows,
    }
    (R25 / "stage-c-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(SLUGS)} fixtures under {FIX}")


if __name__ == "__main__":
    main()
