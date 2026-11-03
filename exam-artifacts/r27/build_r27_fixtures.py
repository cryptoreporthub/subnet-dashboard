#!/usr/bin/env python3
"""Generate r27 fixtures (p5-v2 + 4 fresh PASS), blind packs, stage-c-manifest."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R27 = ROOT / "exam-artifacts/r27"
R25 = ROOT / "exam-artifacts/r25"
FIX = R27 / "fixtures"
BLIND = R27 / "blind"
BASE_SHA = "882980b817986fdcd2766fb18d46525b8e1955fd"

REUSE_FROM_R25 = [
    "p1a",
    "p1b",
    "p2",
    "p3",
    "p4",
    "p6-v2",
    "p7-v3",
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

NEW_SLUGS = ["p5-v2", "p8", "p9", "p10", "p11"]

SLUGS = [
    "p1a",
    "p1b",
    "p2",
    "p3",
    "p4",
    "p5-v2",
    "p6-v2",
    "p7-v3",
    "p8",
    "p9",
    "p10",
    "p11",
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

HEAD_SHAS = {
    "p5-v2": "a27f000000000000000000000000000000000006",
    "p8": "a27f000000000000000000000000000000000015",
    "p9": "a27f000000000000000000000000000000000016",
    "p10": "a27f000000000000000000000000000000000017",
    "p11": "a27f000000000000000000000000000000000018",
}

PR_NUM = {
    "p5-v2": 9626,
    "p8": 9627,
    "p9": 9628,
    "p10": 9629,
    "p11": 9630,
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def make_patch(old: str, new: str) -> tuple[str, int, int]:
    import difflib

    old_lines = old.splitlines()
    new_lines = new.splitlines()
    if old == new:
        return "", 0, 0
    udiff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
    hunks: list[str] = []
    adds = dels = 0
    for line in udiff:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
        if line.startswith("@@") or line.startswith(("+", "-", " ")):
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
        status = "removed" if old and not new else "added" if not old and new else "modified"
        entries.append(
            {
                "path": path,
                "status": status,
                "additions": adds,
                "deletions": dels,
                "patch": patch,
            }
        )
    return {"totalFiles": len(entries), "files": entries, "truncated": False, "omittedPaths": []}


def ci_job_pytest(workflow_name: str, test_path: str) -> str:
    return (
        f"name: {workflow_name}\n"
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: pip install pytest\n"
        f"      - run: pytest -q {test_path}\n"
    )


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


def repo_for(slug: str) -> dict:
    if slug == "p5-v2":
        wf = ci_job_pytest("ci-audit-v2", "tests/test_r27_audit_hook.py")
        tst = (
            "from internal.r27_audit_hook import emit_audit_tick\n\n\n"
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
                ".github/workflows/ci-audit-v2.yml": wf,
                "internal/r27_audit_hook.py": mod,
                "tests/test_r27_audit_hook.py": tst,
            },
            "baseFiles": {},
        }
    if slug == "p8":
        wf = ci_job_pytest("ci-metrics-hook", "tests/test_r27_metrics_hook.py")
        mod = (
            "from __future__ import annotations\n\n\n"
            "def metrics_tick(n: int) -> int:\n"
            "    return n + 3\n"
        )
        tst = (
            "from internal.r27_metrics_hook import metrics_tick\n\n\n"
            "def test_metrics_tick():\n"
            "    assert metrics_tick(2) == 5\n"
        )
        return {
            "files": {
                ".github/workflows/ci-metrics-hook.yml": wf,
                "internal/r27_metrics_hook.py": mod,
                "tests/test_r27_metrics_hook.py": tst,
            },
            "baseFiles": {},
        }
    if slug == "p9":
        wf = ci_job_pytest("ci-cache-helper", "tests/test_r27_cache_helper.py")
        mod = (
            "from __future__ import annotations\n\n\n"
            "def cache_slots(cap: int) -> int:\n"
            "    return cap * 2\n"
        )
        tst = (
            "from internal.r27_cache_helper import cache_slots\n\n\n"
            "def test_cache_slots():\n"
            "    assert cache_slots(4) == 8\n"
        )
        return {
            "files": {
                ".github/workflows/ci-cache-helper.yml": wf,
                "internal/r27_cache_helper.py": mod,
                "tests/test_r27_cache_helper.py": tst,
            },
            "baseFiles": {},
        }
    if slug == "p10":
        wf = ci_job_pytest("ci-intern-hook", "tests/test_r27_intern_hook.py")
        mod = (
            "from __future__ import annotations\n\n\n"
            "def intern_label(label: str) -> str:\n"
            "    return label.strip().lower()\n"
        )
        tst = (
            "from internal.r27_intern_hook import intern_label\n\n\n"
            "def test_intern_label():\n"
            "    assert intern_label('  Foo ') == 'foo'\n"
        )
        return {
            "files": {
                ".github/workflows/ci-intern-hook.yml": wf,
                "internal/r27_intern_hook.py": mod,
                "tests/test_r27_intern_hook.py": tst,
            },
            "baseFiles": {},
        }
    if slug == "p11":
        wf = ci_job_pytest("ci-lint-hook", "tests/test_r27_lint_hook.py")
        mod = (
            "from __future__ import annotations\n\n\n"
            "def lint_score(text: str) -> int:\n"
            "    return len(text.split())\n"
        )
        tst = (
            "from internal.r27_lint_hook import lint_score\n\n\n"
            "def test_lint_score():\n"
            "    assert lint_score('one two three') == 3\n"
        )
        return {
            "files": {
                ".github/workflows/ci-lint-hook.yml": wf,
                "internal/r27_lint_hook.py": mod,
                "tests/test_r27_lint_hook.py": tst,
            },
            "baseFiles": {},
        }
    raise KeyError(slug)


def meta_for(slug: str) -> dict:
    titles = {
        "p5-v2": "test: audit hook job with checkout and python setup",
        "p8": "test: add metrics hook coverage workflow",
        "p9": "test: cache helper module with CI job",
        "p10": "test: string intern helper with CI job",
        "p11": "test: lint score helper with CI job",
    }
    bodies = {
        "p5-v2": "Adds audit hook tests and a workflow with checkout plus setup-python before pytest.",
        "p8": "Introduces a metrics hook module and a properly wired CI job that runs its tests.",
        "p9": "Adds cache helper coverage with checkout, Python setup, and pytest in CI.",
        "p10": "Adds intern helper tests executed by a complete GitHub Actions job.",
        "p11": "Adds lint score helper tests with valid CI wiring (checkout + setup + pytest).",
    }
    return {
        "title": titles[slug],
        "body": bodies[slug],
        "oracle": "PASS",
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
        lang = "python" if path.endswith(".py") else "yaml" if path.endswith((".yml", ".yaml")) else ""
        lines.append(f"### `{path}`")
        lines.append(f"```{lang}".rstrip())
        lines.append(content.rstrip("\n"))
        lines.append("```")
        lines.append("")
    (BLIND / f"{slug}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def manifest_row_from_r25(slug: str) -> dict:
    r25 = json.loads((R25 / "stage-c-manifest.json").read_text())
    for row in r25["fixtures"]:
        if row["slug"] == slug:
            return dict(row)
    raise KeyError(slug)


def write_new_fixture(slug: str) -> dict:
    meta = meta_for(slug)
    repo = repo_for(slug)
    diff = build_diff(repo)
    diff_json = json.dumps(diff, indent=2, sort_keys=False) + "\n"
    diff_sha = sha256_text(diff_json)
    head = HEAD_SHAS[slug]
    gate = gate_doc(head)
    fixture_name = f"r27-{slug}"
    fdir = FIX / fixture_name
    fdir.mkdir(parents=True, exist_ok=True)
    changed = sorted(set(repo.get("files", {})) | set(repo.get("baseFiles", {})))
    changed = [
        p
        for p in changed
        if repo.get("files", {}).get(p, "") != repo.get("baseFiles", {}).get(p, "")
    ]
    pr_num = PR_NUM[slug]
    pr = {
        "number": pr_num,
        "title": meta["title"],
        "body": meta["body"],
        "url": f"https://github.com/cryptoreporthub/subnet-dashboard/pull/{pr_num}",
        "headSha": head,
        "baseSha": BASE_SHA,
        "draft": False,
        "files": changed,
    }
    oracle_doc = {
        "fixture": fixture_name,
        "slug": slug,
        "mechanism": "P" + slug[1] if slug.startswith("p") else "M" + slug[1],
        "variant": slug,
        "baseSha": BASE_SHA,
        "diffSha256": diff_sha,
        "changedPaths": changed,
        "behavior": {"expectedVerdict": "PASS"},
        "labeling": {"consensus": "PASS", "note": "Cursor build; Claude label pending RUN-READY-27"},
        "pytest": {"summary": "52 passed", "passed": 52, "failed": 0, "skipped": 0, "failingTests": []},
    }
    (fdir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n", encoding="utf-8")
    (fdir / "gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    (fdir / "repo.json").write_text(json.dumps(repo, indent=2) + "\n", encoding="utf-8")
    (fdir / "diff.json").write_text(diff_json, encoding="utf-8")
    (fdir / "oracle.json").write_text(json.dumps(oracle_doc, indent=2) + "\n", encoding="utf-8")
    write_blind(slug, meta, gate, diff, repo)
    return {
        "slug": slug,
        "fixture": fixture_name,
        "fixturePath": f"exam-artifacts/r27/fixtures/{fixture_name}",
        "oracle": "PASS",
        "sha256": {
            "diff": diff_sha,
            "oracle": sha256_file(fdir / "oracle.json"),
            "repo": sha256_file(fdir / "repo.json"),
        },
    }


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    BLIND.mkdir(parents=True, exist_ok=True)
    for slug in REUSE_FROM_R25:
        src = R25 / "blind" / f"{slug}.md"
        dst = BLIND / f"{slug}.md"
        if src.is_file():
            shutil.copy2(src, dst)
    manifest_rows = []
    for slug in SLUGS:
        if slug in NEW_SLUGS:
            manifest_rows.append(write_new_fixture(slug))
        else:
            manifest_rows.append(manifest_row_from_r25(slug))
    manifest = {
        "stage": "C",
        "round": "r27",
        "baseSha": BASE_SHA,
        "retired": {"p5": "r25-p5 ambiguous CI wiring (no checkout/setup); replaced by p5-v2"},
        "fixtures": manifest_rows,
        "slotMath": {
            "invocationsPerArm": 5,
            "casesPerInvocation": 24,
            "slotsPerArm": 120,
            "passSlotsPerArm": 60,
            "modifySlotsPerArm": 60,
            "totalSlotsBothArms": 240,
            "formula": "5 invocations/arm × 24 cases = 120 slots/arm; 240 total both arms",
        },
        "bars": {
            "lockRef": "LOCK-C (6593881720), r27 PASS denominator 60",
            "C1": {
                "summary": "PASS over-block cap 4/60 per arm",
                "maxOverBlocksPerArm": 4,
                "passSlotDenominatorPerArm": 60,
                "noPassFixtureBlocked": "No PASS fixture with ≥4 of 5 invocations blocked (per arm)",
                "fisherOneSided": "One-sided Fisher C25 vs R23: p ≥ 0.10",
            },
            "C2": "MODIFY caught C25 >= 50/60",
            "C3": "MODIFY gain C25 vs R23 >= +5 of 60",
            "C4": "Each MODIFY category >= 50% caught under C25",
        },
        "model": "composer-2.5 fast:false both arms (same as r25)",
        "arms": {"R23": "a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e", "C25": "06269de964afc69bc81dd71156caa5bb2594bea1"},
    }
    (R27 / "stage-c-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"r27 manifest: {len(SLUGS)} fixtures ({len(NEW_SLUGS)} new PASS under r27/fixtures/)")


if __name__ == "__main__":
    main()
