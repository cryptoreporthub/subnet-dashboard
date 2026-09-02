"""Patch D correlation script — synthetic fixture must flag ghost-write cases."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.patchd_correlate import correlate_lines, main

FIXTURE = Path("tests/fixtures/patchd_synthetic_raw.log")


def test_synthetic_fixture_has_ghost_write_suspect_and_confirmed():
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    _, flags = correlate_lines(lines)
    kinds = {f.kind for f in flags}
    assert "GHOST-WRITE-SUSPECT" in kinds
    assert "GHOST-WRITE-CONFIRMED" in kinds


def test_confirmed_pairs_daily_pick_work_thread():
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    _, flags = correlate_lines(lines)
    confirmed = [f for f in flags if f.kind == "GHOST-WRITE-CONFIRMED"]
    assert any("daily-pick-work" in (f.thread or "") for f in confirmed)


def test_main_dry_run_writes_correlated_md(tmp_path):
    out = tmp_path / "correlated.md"
    rc = main([str(FIXTURE), "-o", str(out), "--capture-mode", "fixture"])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "GHOST-WRITE-SUSPECT" in body
    assert "GHOST-WRITE-CONFIRMED" in body
    assert "ZERO HITS" not in body


def test_empty_log_fails_loudly(tmp_path):
    raw = tmp_path / "empty.log"
    raw.write_text("", encoding="utf-8")
    rc = main([str(raw), "-o", str(tmp_path / "out.md")])
    assert rc == 2


def test_missing_generation_token_breaks_confirmed_if_stripped(tmp_path):
    """Mutation standard: without thread identity, CONFIRMED must not fire."""
    lines = [
        "2026-09-01T16:00:00Z worker abandoned daily pick tick timed out after 90s",
        "2026-09-01T16:03:00Z pick_score_cache persist predictions.json thread=other-thread",
    ]
    _, flags = correlate_lines(lines)
    assert any(f.kind == "GHOST-WRITE-SUSPECT" for f in flags)
    assert not any(f.kind == "GHOST-WRITE-CONFIRMED" for f in flags)
