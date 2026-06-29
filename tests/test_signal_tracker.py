import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from internal.signals.signal_tracker import SignalTracker
from internal.council.signals.poller import PollerWorker
from internal.council.signals.pathfinder import PathfinderWorker


@pytest.fixture
def tmp_tracker(tmp_path):
    path = tmp_path / "signal_timeline.json"
    tracker = SignalTracker(persistence_path=str(path))
    return tracker


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def test_record_signal_stores_first_signal(tmp_tracker):
    now = datetime.now(timezone.utc)
    result = tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now))
    assert result["first_signal_at"] == _ts(now)
    assert result["first_signal_source"] == "x"
    assert result["state"] == "idle"
    assert result["metrics"]["signal_count"] == 1


def test_pump_starts_with_multiple_sources(tmp_tracker):
    now = datetime.now(timezone.utc)
    tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now))
    tmp_tracker.record_signal("TAO", "discord", timestamp=_ts(now + timedelta(minutes=5)))

    timeline = tmp_tracker.get_timeline("TAO")["data"]
    assert timeline["state"] == "pumping"
    assert timeline["pump_started_at"] is not None
    assert timeline["metrics"]["time_to_pump_seconds"] == 300


def test_pump_ends_after_idle_period(tmp_tracker):
    now = datetime.now(timezone.utc)
    tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now))
    tmp_tracker.record_signal("TAO", "discord", timestamp=_ts(now + timedelta(hours=1)))
    tmp_tracker.record_signal("TAO", "telegram", timestamp=_ts(now + timedelta(hours=2)))
    # gap > 2h ends the pump but is not long enough for a resurgence
    tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now + timedelta(hours=5)))

    timeline = tmp_tracker.get_timeline("TAO")["data"]
    assert timeline["state"] == "pumped"
    assert timeline["pump_ended_at"] is not None
    assert timeline["metrics"]["pump_duration_seconds"] == 3600


def test_resurgence_detected_after_quiet_period(tmp_tracker):
    now = datetime.now(timezone.utc)
    tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now))
    tmp_tracker.record_signal("TAO", "discord", timestamp=_ts(now + timedelta(hours=1)))
    tmp_tracker.record_signal("TAO", "telegram", timestamp=_ts(now + timedelta(hours=2)))
    # quiet period > 6h then resurge
    tmp_tracker.record_signal("TAO", "x", timestamp=_ts(now + timedelta(hours=9)))

    timeline = tmp_tracker.get_timeline("TAO")["data"]
    assert timeline["state"] == "resurging"
    assert timeline["resurgence_at"] is not None
    assert timeline["metrics"]["time_to_resurgence_seconds"] == 25200


def test_unsupported_source_raises(tmp_tracker):
    with pytest.raises(ValueError):
        tmp_tracker.record_signal("TAO", "reddit")


def test_persistence_reloads_state(tmp_path):
    path = tmp_path / "signal_timeline.json"
    tracker = SignalTracker(persistence_path=str(path))
    tracker.record_signal("TAO", "x")

    tracker2 = SignalTracker(persistence_path=str(path))
    data = tracker2.get_timeline("TAO")["data"]
    assert data["metrics"]["signal_count"] == 1


def test_poller_worker_records_signal(tmp_tracker):
    worker = PollerWorker(tracker=tmp_tracker)
    result = worker.poll("HYPE", "telegram")
    assert result["first_signal_source"] == "telegram"


def test_pathfinder_worker_records_signal(tmp_tracker):
    worker = PathfinderWorker(tracker=tmp_tracker)
    result = worker.route("VVV", "news")
    assert result["first_signal_source"] == "news"



