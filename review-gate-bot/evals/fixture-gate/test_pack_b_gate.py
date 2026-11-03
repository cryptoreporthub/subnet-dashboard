"""Pack B gate: author-voice titles and no exam patch duplicates."""
from __future__ import annotations

import json
from pathlib import Path

from gate_core import (
    check_r1b_author_voice,
    check_r1b_exam_duplicate,
    diff_patch_fingerprint,
    exam_patch_fingerprints,
    validate_r1b_fixture_dir,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "review-gate-bot" / "evals" / "fixtures"


def r1b_dirs() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.is_dir() and p.name.startswith("r1b-"))


def test_every_r1b_fixture_passes_author_voice_and_exam_dup_gates() -> None:
    exam_fps = exam_patch_fingerprints(FIXTURES)
    for d in r1b_dirs():
        errors = validate_r1b_fixture_dir(d, exam_fps=exam_fps)
        assert not errors, f"{d.name}: " + "; ".join(errors)


def test_author_voice_gate_rejects_defect_title() -> None:
    errors = check_r1b_author_voice(
        "r1b-f1-99",
        {"title": "universe: omit netuid 0 in filter"},
        {},
    )
    assert errors


def test_author_voice_gate_allows_control() -> None:
    errors = check_r1b_author_voice(
        "r1b-f3-ctrl-99",
        {"title": "tests: skip flake on purpose"},
        {"packBControl": True},
    )
    assert not errors


def test_exam_dup_gate_rejects_known_nonowner_patch() -> None:
    exam = FIXTURES / "hard-planted-nonowner-refresh" / "diff.json"
    fp = diff_patch_fingerprint(json.loads(exam.read_text()))
    errors = check_r1b_exam_duplicate("r1b-f1-99", {"files": [{"patch": json.loads(exam.read_text())["files"][0]["patch"]}]}, {fp})
    assert errors
