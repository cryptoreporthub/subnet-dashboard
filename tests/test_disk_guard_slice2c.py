"""Disk guard, readiness, and chain recorder (#1399 slice 2c)."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.chain_price import config as cfg
from internal.chain_price.sampler import run_forward_sample
from internal.disk_guard import (
    DiskUsage,
    WORKER_VOLUME_OWNER,
    build_data_volume_readiness,
    disk_usage_for_metrics,
    is_low,
    readiness_thresholds_mb,
    refresh_data_volume_metrics_cache_sync,
)
from server import app


def _usage(free: int, used: int = 0, total: int = 1_000_000_000):
    from types import SimpleNamespace

    return SimpleNamespace(total=total, used=used, free=free)


def test_is_low_respects_floor(monkeypatch):
    monkeypatch.setattr(
        "internal.disk_guard.data_volume_usage",
        lambda: _usage(free=150 * 1024 * 1024),
    )
    assert is_low(200) is True
    assert is_low(100) is False


def test_is_low_missing_db_parent_uses_existing_ancestor(tmp_path, monkeypatch):
    db_file = tmp_path / "no" / "such" / "chain_prices.db"
    assert not db_file.parent.exists()

    def _low_on_root(directory: str):
        if os.path.samefile(directory, str(tmp_path)):
            return DiskUsage(free=10 * 1024 * 1024, used=0, total=1_000_000_000)
        from internal.disk_guard import data_volume_usage_for_path

        return data_volume_usage_for_path(directory)

    monkeypatch.setattr("internal.disk_guard.data_volume_usage_for_path", _low_on_root)
    assert is_low(200, path=str(db_file)) is True


def test_is_low_uses_db_parent_directory(tmp_path):
    db_file = tmp_path / "nested" / "chain_prices.db"
    db_file.parent.mkdir()
    db_file.write_text("")
    with patch("internal.disk_guard.data_volume_usage_for_path") as probe:
        probe.return_value = DiskUsage(free=50 * 1024 * 1024, used=0, total=100)
        assert is_low(200, path=str(db_file)) is True
        probe.assert_called_once_with(str(db_file.parent))


def test_readiness_thresholds_follow_chain_price_min_free_mb(monkeypatch):
    import internal.disk_guard as dg

    monkeypatch.setattr(dg, "CHAIN_PRICE_MIN_FREE_MB", 500)
    monkeypatch.setattr(dg, "chain_price_warn_extra_mb", lambda: 50)
    low, warn = readiness_thresholds_mb()
    assert low == 500
    assert warn == 550


def test_invalid_chain_price_env_falls_back_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("CHAIN_PRICE_MIN_FREE_MB", "not-a-number")
    assert cfg._int_env("CHAIN_PRICE_MIN_FREE_MB", 200) == 200
    assert "invalid CHAIN_PRICE_MIN_FREE_MB" in caplog.text


def test_readiness_data_volume_low_when_mounted(monkeypatch):
    monkeypatch.setattr(cfg, "CHAIN_PRICE_MIN_FREE_MB", 200)
    monkeypatch.setattr(
        "internal.disk_guard.data_dir_is_mounted_volume",
        lambda: True,
    )
    monkeypatch.setattr(
        "internal.disk_guard.data_volume_usage",
        lambda: _usage(free=200 * 1024 * 1024 - 1),
    )
    block = build_data_volume_readiness()
    assert block["mounted"] is True
    assert block["low"] is True
    assert block["min_free_mb"] == 200

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert "data_volume_low" in report["issues"]
    assert report["data_volume"]["low"] is True


def test_readiness_not_mounted_skips_issue(monkeypatch):
    monkeypatch.setattr(
        "internal.disk_guard.data_dir_is_mounted_volume",
        lambda: False,
    )
    monkeypatch.setattr(
        "internal.disk_guard.data_volume_usage",
        lambda: _usage(free=1024),
    )
    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert report["data_volume"]["mounted"] is False
    assert "data_volume_low" not in report["issues"]


def test_split_v2_proxies_worker_low_volume(monkeypatch):
    monkeypatch.setattr(cfg, "CHAIN_PRICE_MIN_FREE_MB", 200)
    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: True)
    worker_block = {
        "owner": WORKER_VOLUME_OWNER,
        "mounted": True,
        "path": "/app/data",
        "free_bytes": 50 * 1024 * 1024,
        "used_bytes": 900 * 1024 * 1024,
        "total_bytes": 1024 * 1024 * 1024,
        "low": True,
        "warn": True,
        "min_free_mb": 200,
        "warn_free_mb": 300,
    }

    def _fetch(path: str, **_kwargs):
        assert path == "/api/ops/data-volume"
        return worker_block

    monkeypatch.setattr("internal.worker_proxy.fetch_worker_json_sync", _fetch)

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert report["data_volume"]["owner"] == "worker_proxy"
    assert report["data_volume"]["low"] is True
    assert "data_volume_low" in report["issues"]


def test_split_v2_worker_mounted_false_unavailable(monkeypatch):
    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: True)

    def _fetch(path: str, **_kwargs):
        return {"owner": WORKER_VOLUME_OWNER, "mounted": False, "path": "/app/data"}

    monkeypatch.setattr("internal.worker_proxy.fetch_worker_json_sync", _fetch)

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert report["data_volume"]["status"] == "unavailable"
    assert "data_volume_unavailable" in report["issues"]


def test_split_v2_misrouted_worker_reply_unavailable(monkeypatch):
    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: True)

    def _fetch(path: str, **_kwargs):
        return {"owner": "web_local", "mounted": True, "free_bytes": 1}

    monkeypatch.setattr("internal.worker_proxy.fetch_worker_json_sync", _fetch)

    block = build_data_volume_readiness()
    assert block["status"] == "unavailable"


def test_split_v2_worker_unavailable(monkeypatch):
    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: True)

    def _fail(path: str, **_kwargs):
        raise ConnectionError("worker down")

    monkeypatch.setattr("internal.worker_proxy.fetch_worker_json_sync", _fail)

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert report["data_volume"]["status"] == "unavailable"
    assert "data_volume_unavailable" in report["issues"]
    assert "data_volume_low" not in report["issues"]


def test_missing_db_parent_disk_low_e2e_no_schema_write(tmp_path):
    db_path = tmp_path / "nested" / "chain_prices.db"
    assert not db_path.parent.exists()

    class _Client:
        def _call(self, method, params=None):
            raise RuntimeError("should not reach RPC")

    def _low_on_root(directory: str):
        if os.path.samefile(directory, str(tmp_path)):
            return DiskUsage(free=10 * 1024 * 1024, used=0, total=1_000_000_000)
        from internal.disk_guard import data_volume_usage_for_path

        return data_volume_usage_for_path(directory)

    with patch.object(cfg, "forward_record_enabled", return_value=True), patch(
        "internal.disk_guard.data_volume_usage_for_path",
        _low_on_root,
    ):
        result = run_forward_sample(_Client(), db_path=str(db_path), write=True)
    assert result["outcome"] == "disk_low"
    assert not db_path.exists()


def test_missing_db_parent_no_ancestor_returns_db_unavailable():
    db_path = "/this/path/should/not/exist/at/all/chain_prices.db"

    class _Client:
        def _call(self, method, params=None):
            raise RuntimeError("should not reach RPC")

    with patch.object(cfg, "forward_record_enabled", return_value=True), patch(
        "internal.disk_guard.nearest_existing_directory",
        return_value=None,
    ):
        result = run_forward_sample(_Client(), db_path=db_path, write=True)
    assert result["outcome"] == "db_unavailable"


def test_recorder_disk_low_no_write_no_auto_cancel(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chain_prices.db")

    class _BrokenClient:
        def _call(self, method, params=None):
            raise RuntimeError("should not reach RPC when disk_low")

    monkeypatch.setattr("internal.chain_price.sampler.is_low", lambda _mb, **_: True)
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        import internal.chain_price.sampler as sampler_mod

        sampler_mod._consecutive_hard_failures = 0
        for _ in range(8):
            result = run_forward_sample(_BrokenClient(), db_path=db_path, write=True)
            assert result["outcome"] == "disk_low"
        assert sampler_mod._consecutive_hard_failures == 0

    assert not __import__("os").path.isfile(db_path)


def test_disk_low_scheduler_tick_does_not_stop_recorder(monkeypatch):
    stopped: list[int] = []

    monkeypatch.setattr(
        "internal.chain_price.scheduler.stop_forward_recorder",
        lambda: stopped.append(1),
    )
    monkeypatch.setattr("internal.chain_price.sampler.is_low", lambda _mb, **_: True)
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        from internal.chain_price.scheduler import _tick

        for _ in range(8):
            _tick()
    assert not stopped


def test_metrics_exposes_data_volume_gauges(monkeypatch):
    refresh_data_volume_metrics_cache_sync = __import__(
        "internal.disk_guard", fromlist=["refresh_data_volume_metrics_cache_sync"]
    ).refresh_data_volume_metrics_cache_sync
    monkeypatch.setattr(
        "internal.disk_guard._probe_disk_usage_for_metrics",
        lambda: DiskUsage(free=111, used=222, total=333),
    )
    refresh_data_volume_metrics_cache_sync()
    from internal.metrics import refresh_from_state

    refresh_from_state()
    from internal.metrics import (
        DATA_VOLUME_FREE_BYTES,
        DATA_VOLUME_METRICS_OK,
        DATA_VOLUME_TOTAL_BYTES,
        DATA_VOLUME_USED_BYTES,
    )

    assert DATA_VOLUME_FREE_BYTES._value.get() == 111
    assert DATA_VOLUME_USED_BYTES._value.get() == 222
    assert DATA_VOLUME_TOTAL_BYTES._value.get() == 333
    assert DATA_VOLUME_METRICS_OK._value.get() == 1


def test_metrics_clear_stale_values_on_probe_failure(monkeypatch):
    from internal.metrics import (
        DATA_VOLUME_BYTES_UNAVAILABLE,
        DATA_VOLUME_FREE_BYTES,
        DATA_VOLUME_METRICS_OK,
        DATA_VOLUME_TOTAL_BYTES,
        DATA_VOLUME_USED_BYTES,
        refresh_from_state,
    )

    monkeypatch.setattr(
        "internal.disk_guard._probe_disk_usage_for_metrics",
        lambda: DiskUsage(free=999, used=1, total=1000),
    )
    refresh_data_volume_metrics_cache_sync()
    refresh_from_state()
    assert DATA_VOLUME_FREE_BYTES._value.get() == 999
    assert DATA_VOLUME_METRICS_OK._value.get() == 1

    def _raise_connection() -> DiskUsage:
        raise ConnectionError("worker down")

    monkeypatch.setattr("internal.disk_guard._probe_disk_usage_for_metrics", _raise_connection)
    refresh_data_volume_metrics_cache_sync()
    refresh_from_state()
    assert DATA_VOLUME_FREE_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_USED_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_TOTAL_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_METRICS_OK._value.get() == 0


def test_metrics_not_mounted_returns_none(monkeypatch):
    monkeypatch.setattr("internal.data_volume.needs_worker_volume_proxy", lambda: False)
    monkeypatch.setattr("internal.disk_guard.data_dir_is_mounted_volume", lambda: False)
    from internal.disk_guard import _probe_disk_usage_for_metrics

    assert _probe_disk_usage_for_metrics() is None


def test_metrics_refresh_does_not_sync_probe_worker(monkeypatch):
    sync_probes: list[int] = []

    def _probe() -> DiskUsage:
        sync_probes.append(1)
        return DiskUsage(free=42, used=1, total=100)

    monkeypatch.setattr("internal.disk_guard._probe_disk_usage_for_metrics", _probe)
    refresh_data_volume_metrics_cache_sync()
    sync_probes.clear()

    from internal.metrics import refresh_from_state

    refresh_from_state()
    assert sync_probes == []
