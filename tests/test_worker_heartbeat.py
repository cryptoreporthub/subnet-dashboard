"""Inline worker heartbeat tests."""

from __future__ import annotations

from internal.worker_heartbeat import is_alive, read_heartbeat, touch_heartbeat


def test_heartbeat_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "beat.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))

    touch_heartbeat()
    assert read_heartbeat() is not None
    assert is_alive(max_age_seconds=60) is True


def test_heartbeat_stale(tmp_path, monkeypatch):
    path = tmp_path / "beat.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))

    path.write_text(
        '{"pid": 1, "ts": "2020-01-01T00:00:00Z", "run_mode": "worker"}',
        encoding="utf-8",
    )
    assert is_alive(max_age_seconds=10) is False
