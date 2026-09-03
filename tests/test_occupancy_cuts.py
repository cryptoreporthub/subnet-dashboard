"""Occupancy cuts: rank-2 load-inside-90s, (e) commit_ok, rank-3 scoring deadline."""

from __future__ import annotations

import json
import time

import pytest

import internal.council.pick_scheduler as pick_scheduler
from internal.council import daily_pick, daily_pick_engine
from tests.test_pick_scheduler import _arm_daily_sched
from tests.test_dpick_parallel_fetch import _fake_score, _make_subnet


@pytest.fixture(autouse=True)
def isolate_liveness_persistence(tmp_path, monkeypatch):
    from internal import liveness as _liv_mod

    sm_path = tmp_path / "liveness_soul_map.json"

    def _read():
        try:
            return json.loads(sm_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write(mutator):
        blob = _read() or {}
        mutator(blob)
        sm_path.parent.mkdir(parents=True, exist_ok=True)
        sm_path.write_text(json.dumps(blob), encoding="utf-8")

    monkeypatch.setattr(_liv_mod, "write_soul_map", _write)
    monkeypatch.setattr(_liv_mod, "read_soul_map", _read)


def test_daily_tick_timeout_covers_subnet_load(monkeypatch):
    """Rank 2: hanging _load_capped_subnets is inside the 90s future, not APScheduler."""
    pick_scheduler.stop_pick_schedulers()

    def _hang_load():
        time.sleep(8)
        return [{"netuid": 1}]

    monkeypatch.setattr(pick_scheduler, "_load_capped_subnets", _hang_load)
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: False)
    monkeypatch.setattr(pick_scheduler, "_write_scheduler_state", lambda extra=None: None)
    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.write_scheduler_hold",
        lambda reason: {
            "action": "HOLD",
            "date": "2026-08-30",
            "scheduler_hold": True,
        },
    )
    pick_scheduler.DAILY_PICK_TICK_TIMEOUT_SECONDS = 5

    sched = pick_scheduler.DailyPickScheduler()
    _arm_daily_sched(sched)
    t0 = time.monotonic()
    result = sched._tick(reschedule=False)
    elapsed = time.monotonic() - t0
    assert elapsed < 8
    assert "timed out" in str(result.get("error") or "")
    assert result.get("duration_ms", 0) >= 1500
    assert result.get("scheduler_hold") is True


def test_commit_ok_false_skips_json_save(tmp_path, monkeypatch):
    """(e) abandoned generation must not persist daily_picks.json."""
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr(daily_pick_engine, "DAILY_PICKS_PATH", str(path))
    saves = {"n": 0}
    orig = daily_pick_engine._save

    def _count_save(records, path=None):
        saves["n"] += 1
        return orig(records, path)

    monkeypatch.setattr(daily_pick_engine, "_save", _count_save)
    out = daily_pick_engine.get_or_create_today_pick([], {}, commit_ok=lambda: False)
    assert out["action"] == "HOLD"
    assert saves["n"] == 0
    assert not path.exists()


def test_select_daily_pick_deadline_returns_hold_payload(monkeypatch, tmp_path):
    """Rank 3: scoring deadline returns a real low-confidence payload instead of hanging."""
    monkeypatch.setattr(daily_pick, "LATENCY_PATH", str(tmp_path / "lat.jsonl"))
    from internal.council import pick_score_cache

    cache_path = tmp_path / "pick_score_cache.json"
    monkeypatch.setattr(pick_score_cache, "CACHE_PATH", str(cache_path))
    monkeypatch.setattr(pick_score_cache, "LOCK_PATH", str(cache_path) + ".lock")
    pick_score_cache.clear_for_tests()

    def _slow(sn, market_context):
        time.sleep(0.4)
        return _fake_score(sn, market_context)

    monkeypatch.setattr(daily_pick, "score_subnet_for_day", _slow)
    subnets = [_make_subnet(1), _make_subnet(2)]
    t0 = time.monotonic()
    pick = daily_pick.select_daily_pick(
        subnets, {}, deadline_monotonic=time.monotonic() + 0.15
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5
    assert float(pick.get("final_confidence") or 0) == 0.0
    concerns = (pick.get("audit") or {}).get("concerns") or []
    assert any("deadline" in str(c).lower() for c in concerns)
