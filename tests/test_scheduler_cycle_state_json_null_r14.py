"""PR #1485 R14: present JSON null → unreadable (Replit P2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scheduler_cycle_state import (
    CycleStateUnreadableError,
    read_last_cycle_with_status,
    scheduler_state_path,
)


def _wire_paths(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    state = tmp_path / "score_snapshot_scheduler.json"
    monkeypatch.setenv("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH", str(state))
    return soul, state


def _assert_unreadable_with_active_tick_probe_unknown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    _summary, status = read_last_cycle_with_status()
    assert status == "unreadable"
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()


def test_absent_keys_still_missing_not_unreadable(tmp_path, monkeypatch):
    _wire_paths(tmp_path, monkeypatch)
    assert read_last_cycle_with_status() == ({}, "missing")
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", True)
    with pytest.raises(CycleStateUnreadableError):
        snaps.producer_tick_progress()
    monkeypatch.setattr(snaps, "_TICK_ACTIVE", False)
    assert snaps.producer_tick_progress() is None


def test_new_file_last_cycle_null_is_unreadable(tmp_path, monkeypatch):
    _, state = _wire_paths(tmp_path, monkeypatch)
    state.write_text(json.dumps({"last_cycle": None}), encoding="utf-8")
    _assert_unreadable_with_active_tick_probe_unknown(tmp_path, monkeypatch)


def test_legacy_score_snapshot_scheduler_null_is_unreadable(tmp_path, monkeypatch):
    soul, _ = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(json.dumps({"score_snapshot_scheduler": None}), encoding="utf-8")
    _assert_unreadable_with_active_tick_probe_unknown(tmp_path, monkeypatch)


def test_legacy_last_cycle_null_is_unreadable(tmp_path, monkeypatch):
    soul, _ = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(
        json.dumps({"score_snapshot_scheduler": {"last_cycle": None}}),
        encoding="utf-8",
    )
    _assert_unreadable_with_active_tick_probe_unknown(tmp_path, monkeypatch)


def test_new_file_null_takes_precedence_over_legacy_ok(tmp_path, monkeypatch):
    """Unreadable new file must not fall back to legacy ok when new file has null last_cycle."""
    soul, state = _wire_paths(tmp_path, monkeypatch)
    soul.write_text(
        json.dumps(
            {
                "score_snapshot_scheduler": {
                    "last_cycle": {
                        "run_at": "2026-01-01T00:00:00Z",
                        "ok": True,
                        "phase": "scoring",
                        "progress": "1/1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    state.write_text(json.dumps({"last_cycle": None}), encoding="utf-8")
    _assert_unreadable_with_active_tick_probe_unknown(tmp_path, monkeypatch)
