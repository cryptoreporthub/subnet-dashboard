"""Abandoned daily-pick workers must not replace a newer today row."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import internal.council.daily_pick_engine as engine


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_older_build_does_not_clobber_newer_today(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr(engine, "DAILY_PICKS_PATH", str(path))
    now = datetime.now(timezone.utc)
    yesterday = (_today() and (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    newer = {
        "date": _today(),
        "action": "LONG",
        "pick": {"netuid": 8},
        "build_started_at": _iso(now),
        "timestamp_utc": _iso(now),
    }
    engine._save([{"date": yesterday, "action": "HOLD"}])
    engine._save([newer])
    wrote = engine._save(
        [
            {
                "date": _today(),
                "action": "LONG",
                "pick": {"netuid": 99},
                "build_started_at": _iso(now - timedelta(seconds=30)),
                "timestamp_utc": _iso(now + timedelta(seconds=5)),
            }
        ]
    )
    assert wrote is False
    saved = json.loads(path.read_text(encoding="utf-8"))
    today = [row for row in saved if row["date"] == _today()]
    assert len(today) == 1
    assert today[0]["action"] == "LONG"
    assert today[0]["pick"]["netuid"] == 8
    assert any(row["date"] == yesterday for row in saved)


def test_timeout_hold_beats_abandoned_worker(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr(engine, "DAILY_PICKS_PATH", str(path))
    monkeypatch.setattr(engine, "publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        engine,
        "directional_publish_guard",
        lambda _pick: {"approved": True, "reason": ""},
    )
    recorded = {"n": 0}
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: recorded.__setitem__("n", recorded["n"] + 1),
    )
    started = threading.Event()
    release = threading.Event()

    def slow_select(_subnets, _ctx):
        started.set()
        assert release.wait(timeout=5)
        return {
            "action": "long",
            "final_confidence": 0.9,
            "subnet": {"netuid": 54, "price": 1.0},
        }

    monkeypatch.setattr(engine, "select_daily_pick", slow_select)
    holder = {}

    def run():
        holder["out"] = engine.get_or_create_today_pick(
            [{"netuid": 54, "price": 1.0}],
            {},
        )

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=5)
    hold = engine.write_scheduler_hold("daily pick tick timed out after 90s")
    release.set()
    thread.join(timeout=5)
    assert thread.is_alive() is False

    saved = json.loads(path.read_text(encoding="utf-8"))
    today = [row for row in saved if row.get("date") == _today()]
    assert len(today) == 1
    assert today[0]["scheduler_hold"] is True
    assert today[0]["reason"] == hold["reason"]
    assert holder["out"]["scheduler_hold"] is True
    assert recorded["n"] == 0


def test_cancelled_worker_skips_save_and_prediction(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr(engine, "DAILY_PICKS_PATH", str(path))
    monkeypatch.setattr(engine, "publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        engine,
        "directional_publish_guard",
        lambda _pick: {"approved": True, "reason": ""},
    )
    save_calls = {"n": 0}
    real_save = engine._save

    def counting_save(records, save_path=None):
        save_calls["n"] += 1
        return real_save(records, save_path)

    monkeypatch.setattr(engine, "_save", counting_save)
    recorded = {"n": 0}
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: recorded.__setitem__("n", recorded["n"] + 1),
    )
    monkeypatch.setattr(
        engine,
        "select_daily_pick",
        lambda _subnets, _ctx: {
            "action": "long",
            "final_confidence": 0.9,
            "subnet": {"netuid": 54, "price": 1.0},
        },
    )

    out = engine.get_or_create_today_pick(
        [{"netuid": 54, "price": 1.0}],
        {},
        is_cancelled=lambda: True,
    )

    assert out is None
    assert save_calls["n"] == 0
    assert not path.exists()
    assert recorded["n"] == 0
