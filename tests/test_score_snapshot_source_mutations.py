"""Source-level mutation killers on real server/snapshot code (#1484 act-on 5)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


@pytest.fixture(autouse=True)
def _reset_top_picks_cache(monkeypatch):
    import server

    # A fresh lock per test: never release a lock this fixture did not acquire.
    monkeypatch.setattr(server, "_TOP_PICKS_LOCK", threading.Lock())
    server._TOP_PICKS_CACHE.update(at=0.0, payload=None)
    yield
    server._TOP_PICKS_CACHE.update(at=0.0, payload=None)


@pytest.fixture
def seeded_volume(tmp_path, monkeypatch):
    payload = complete_snapshot_payload(
        day_rows=[
            {
                "netuid": 1,
                "total_score": 10.0,
                "name": "One",
                "expert_contributions": {"quant": 0.5, "hype": 0.4},
            }
        ],
        hour_rows=[
            {
                "netuid": 1,
                "total_score": 10.0,
                "name": "One",
                "expert_contributions": {"quant": 0.5, "hype": 0.4},
            }
        ],
    )
    path = tmp_path / "volume.json"
    snaps.publish_complete_snapshot(payload, str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    return path


def test_busy_lock_returns_snapshot_picks(seeded_volume, monkeypatch):
    import server

    server._TOP_PICKS_CACHE.update(at=0, payload=None)
    held = threading.Event()
    release = threading.Event()

    def _block():
        held.set()
        release.wait(timeout=5)

    monkeypatch.setattr(server, "_build_top_picks", _block)
    t = threading.Thread(target=lambda: None)
    assert server._TOP_PICKS_LOCK.acquire(blocking=False)
    try:
        out = server._build_top_picks_cached()
        assert out.get("day_picks"), "busy must serve snapshot picks"
        assert out.get("meta", {}).get("fallback_status") == "busy"
    finally:
        server._TOP_PICKS_LOCK.release()


def test_api_top_picks_timeout_returns_snapshot(seeded_volume, monkeypatch):
    import server

    monkeypatch.setattr(server, "PICK_HANDLER_TIMEOUT", 0.001)

    def _slow():
        time.sleep(0.05)
        return {"hour_picks": [], "day_picks": [], "status": "pending_snapshot"}

    monkeypatch.setattr(server, "_build_top_picks", _slow)
    client = TestClient(server.app)
    resp = client.get("/api/top-picks")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("day_picks"), "timeout must fall back to snapshot"


def test_api_top_picks_exception_returns_snapshot(seeded_volume, monkeypatch):
    import server

    def _boom():
        raise RuntimeError("hydrate blew up")

    monkeypatch.setattr(server, "_build_top_picks", _boom)
    client = TestClient(server.app)
    resp = client.get("/api/top-picks")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("day_picks")


def test_pending_snapshot_not_cached_on_next_call(seeded_volume, monkeypatch):
    import server

    pending = {
        "hour_picks": [],
        "day_picks": [],
        "status": "pending_snapshot",
        "meta": {"source": "score_snapshot"},
    }
    server._TOP_PICKS_CACHE.update(payload=pending, at=time.time())
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        if calls["n"] == 1:
            return pending
        return server._snapshot_only_top_picks("busy")

    monkeypatch.setattr(server, "_build_top_picks", _build)
    out = server._build_top_picks_cached()
    assert out.get("status") == "pending_snapshot"
    assert server._TOP_PICKS_CACHE.get("payload") is pending
    second = server._build_top_picks_cached()
    assert second.get("day_picks"), "must not serve stale pending from TTL cache"


def test_atomic_write_sigkill_preserves_previous_file(tmp_path):
    path = tmp_path / "snap.json"
    good = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    snaps.publish_complete_snapshot(good, str(path))
    before = path.read_bytes()
    repo = os.path.dirname(os.path.dirname(os.path.abspath(snaps.__file__)))
    code = f"""
import os, sys
sys.path.insert(0, {repr(repo)})
os.environ['SCORE_SNAPSHOT_ATOMIC_TEST_HOOK'] = 'sigkill_after_tmp_write'
from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload
snaps.SCORE_SNAPSHOTS_PATH = {repr(str(path))}
payload = complete_snapshot_payload(day_rows=[{{"netuid": 99, "total_score": 99.0}}])
snaps.publish_complete_snapshot(payload, snaps.SCORE_SNAPSHOTS_PATH)
"""
    proc = subprocess.Popen([sys.executable, "-c", code])
    proc.wait(timeout=10)
    assert proc.returncode < 0 or proc.returncode != 0
    assert path.read_bytes() == before


def test_atomic_write_calls_fsync(tmp_path, monkeypatch):
    path = tmp_path / "snap.json"
    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    calls = {"fsync": 0}
    real_fsync = os.fsync

    def _count_fsync(fd):
        calls["fsync"] += 1
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", _count_fsync)
    snaps.publish_complete_snapshot(payload, str(path))
    assert calls["fsync"] >= 1
