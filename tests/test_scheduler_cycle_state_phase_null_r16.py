"""PR #1485 R16: ``phase: null`` backward compat + W2 writer omits null ``progress``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import read_last_cycle_with_status, scheduler_state_path

# Shape persisted by pre-r15 writers (1ada719b / main / #1486): explicit JSON nulls on idle fields.
PRE_R15_WRITER_LAST_CYCLE = {
    "run_id": None,
    "run_at": "2026-10-30T12:00:00Z",
    "ok": False,
    "published": None,
    "complete": None,
    "count": None,
    "written_at": None,
    "path": None,
    "error": None,
    "skipped": "heavy_job_busy",
    "phase": None,
    "progress": None,
}


def _wire_paths(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    return soul, state


def test_pre_r15_writer_shape_reads_ok_on_new_file(tmp_path, monkeypatch):
    """Fails on ``87cfcc0``: r15 validator treated ``phase: null`` as unreadable."""
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(json.dumps({"last_cycle": PRE_R15_WRITER_LAST_CYCLE}), encoding="utf-8")
    summary, status = read_last_cycle_with_status()
    assert status == "ok"
    assert summary.get("skipped") == "heavy_job_busy"
    assert summary.get("phase") is None


def test_pre_r15_writer_shape_reads_ok_on_legacy_file(tmp_path, monkeypatch):
    soul, state = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(
        json.dumps({"score_snapshot_scheduler": {"last_cycle": PRE_R15_WRITER_LAST_CYCLE}}),
        encoding="utf-8",
    )
    state.write_text("{}", encoding="utf-8")
    summary, status = read_last_cycle_with_status()
    assert status == "ok"
    assert summary.get("skipped") == "heavy_job_busy"


def test_phase_null_is_readable_like_absent_phase(tmp_path, monkeypatch):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(
        json.dumps({"last_cycle": {"run_at": "t", "ok": False, "phase": None}}),
        encoding="utf-8",
    )
    assert read_last_cycle_with_status()[1] == "ok"


def _last_cycle_on_disk(tmp_path, monkeypatch) -> dict:
    path = Path(scheduler_state_path())
    return json.loads(path.read_text(encoding="utf-8"))["last_cycle"]


def test_persist_cycle_summary_omits_null_progress_key(tmp_path, monkeypatch):
    """W2: writer must not persist ``\"progress\": null`` (legacy volumes omit the key)."""
    _wire_paths(tmp_path, monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    sched._persist_cycle_summary(
        {
            "run_id": "r1",
            "run_at": snaps._now_iso(),
            "ok": False,
            "phase": "scoring",
            "progress": None,
        }
    )
    last = _last_cycle_on_disk(tmp_path, monkeypatch)
    assert "progress" not in last
    assert last.get("phase") == "scoring"


def test_w2_mutation_retaining_null_progress_key_fails_omit_contract(tmp_path, monkeypatch):
    """Simulate removing the progress ``None`` drop in ``_persist_cycle_summary``."""
    _wire_paths(tmp_path, monkeypatch)
    real = snaps.ScoreSnapshotScheduler._persist_cycle_summary

    def _w2_mutant(self, result):
        from internal.council.scheduler_cycle_state import write_last_cycle

        summary = {
            "run_id": result.get("run_id"),
            "run_at": result.get("run_at"),
            "ok": bool(result.get("ok")),
            "published": result.get("published"),
            "complete": result.get("complete"),
            "count": result.get("count"),
            "written_at": result.get("written_at"),
            "path": result.get("path"),
            "error": result.get("error"),
            "skipped": result.get("skipped"),
            "phase": result.get("phase"),
            "progress": result.get("progress"),
        }
        if summary.get("phase") is None:
            summary.pop("phase", None)
        write_last_cycle(summary)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", _w2_mutant)

    def _assert_omits_null_progress():
        sched = snaps.ScoreSnapshotScheduler()
        sched._persist_cycle_summary(
            {
                "run_id": "r1",
                "run_at": snaps._now_iso(),
                "ok": False,
                "progress": None,
            }
        )
        last = _last_cycle_on_disk(tmp_path, monkeypatch)
        assert "progress" not in last

    with pytest.raises(AssertionError):
        _assert_omits_null_progress()

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", real)
    _assert_omits_null_progress()
