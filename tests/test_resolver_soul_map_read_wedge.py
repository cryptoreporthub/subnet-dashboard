"""Regression: corrupt soul_map must not wedge resolver bootstrap reads."""

from __future__ import annotations

import pytest

from internal.council import resolver_scheduler, weights


def test_corrupt_soul_map_does_not_wedge_cycle_generation_seed(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))

    sched = resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(soul), refresh_minutes=15
    )
    sched._ensure_cycle_generation_seeded()
    assert sched._cycle_generation_seeded is True


def test_load_json_degrades_unreadable_to_empty_dict(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{broken", encoding="utf-8")
    assert resolver_scheduler._load_json(str(soul)) == {}


def test_persist_honesty_preserves_existing_cycle_error():
    sched = resolver_scheduler.PredictionResolverScheduler(refresh_minutes=15)
    result = {"ok": True, "error": "resolve phase failed"}
    sched._apply_persist_honesty(
        result,
        resolver_scheduler.PersistResult(skipped_not_owner=True),
    )
    assert result["error"] == "resolve phase failed"
    assert result.get("skipped") == "persist_skipped"
