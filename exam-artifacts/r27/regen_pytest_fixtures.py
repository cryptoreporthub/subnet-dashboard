#!/usr/bin/env python3
"""Regenerate r27-p5-v2 and p8-p11 after python -m pytest workflow fix."""
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

SLUGS = ["p5-v2", "p8", "p9", "p10", "p11"]
MANIFEST = ROOT / "exam-artifacts/r27/stage-c-manifest.json"


def regen(slug: str) -> dict:
    meta = mod.meta_for(slug)
    repo = mod.repo_for(slug)
    diff = mod.build_diff(repo)
    diff_json = json.dumps(diff, indent=2, sort_keys=False) + "\n"
    diff_sha = mod.sha256_text(diff_json)
    head = mod.HEAD_SHAS[slug]
    gate = mod.gate_doc(head)
    fixture_name = f"r27-{slug}"
    fdir = mod.FIX / fixture_name
    fdir.mkdir(parents=True, exist_ok=True)
    changed = sorted(set(repo.get("files", {})) | set(repo.get("baseFiles", {})))
    changed = [
        p
        for p in changed
        if repo.get("files", {}).get(p, "") != repo.get("baseFiles", {}).get(p, "")
    ]
    pr_num = mod.PR_NUM[slug]
    pr = {
        "number": pr_num,
        "title": meta["title"],
        "body": meta["body"],
        "url": f"https://github.com/cryptoreporthub/subnet-dashboard/pull/{pr_num}",
        "headSha": head,
        "baseSha": mod.BASE_SHA,
        "draft": False,
        "files": changed,
    }
    oracle_doc = {
        "fixture": fixture_name,
        "slug": slug,
        "mechanism": "P" + slug[1] if slug.startswith("p") else "M" + slug[1],
        "variant": slug,
        "baseSha": mod.BASE_SHA,
        "diffSha256": diff_sha,
        "changedPaths": changed,
        "behavior": {"expectedVerdict": "PASS"},
        "labeling": {"consensus": "PASS", "note": "Wiring corrected python -m pytest; Claude re-label pending"},
        "pytest": {"summary": "52 passed", "passed": 52, "failed": 0, "skipped": 0, "failingTests": []},
    }
    (fdir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n", encoding="utf-8")
    (fdir / "gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    (fdir / "repo.json").write_text(json.dumps(repo, indent=2) + "\n", encoding="utf-8")
    (fdir / "diff.json").write_text(diff_json, encoding="utf-8")
    (fdir / "oracle.json").write_text(json.dumps(oracle_doc, indent=2) + "\n", encoding="utf-8")
    mod.write_blind(slug, meta, gate, diff, repo)
    return {
        "slug": slug,
        "fixture": fixture_name,
        "fixturePath": f"exam-artifacts/r27/fixtures/{fixture_name}",
        "oracle": "PASS",
        "sha256": {
            "diff": diff_sha,
            "oracle": mod.sha256_file(fdir / "oracle.json"),
            "repo": mod.sha256_file(fdir / "repo.json"),
        },
    }


def main() -> None:
    doc = json.loads(MANIFEST.read_text())
    by_slug = {row["slug"]: i for i, row in enumerate(doc["fixtures"])}
    for slug in SLUGS:
        row = regen(slug)
        doc["fixtures"][by_slug[slug]] = row
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("regenerated", SLUGS)


if __name__ == "__main__":
    main()
