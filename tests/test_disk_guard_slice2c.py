"""Disk guard, readiness, and chain recorder (#1399 slice 2c)."""

from __future__ import annotations

from unittest.mock import patch

from internal.chain_price import config as cfg
from internal.chain_price.sampler import run_forward_sample
from internal.disk_guard import build_data_volume_readiness, is_low, readiness_thresholds_mb


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


def test_readiness_thresholds_follow_chain_price_min_free_mb(monkeypatch):
    monkeypatch.setattr(cfg, "CHAIN_PRICE_MIN_FREE_MB", 500)
    low, warn = readiness_thresholds_mb()
    assert low == 500
    assert warn == 600


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


def test_recorder_disk_low_no_write_no_auto_cancel(tmp_path, monkeypatch):
    db_path = str(tmp_path / "chain_prices.db")

    class _BrokenClient:
        def _call(self, method, params=None):
            raise RuntimeError("should not reach RPC when disk_low")

    monkeypatch.setattr("internal.chain_price.sampler.is_low", lambda _mb: True)
    with patch.object(cfg, "forward_record_enabled", return_value=True):
        import internal.chain_price.sampler as sampler_mod

        sampler_mod._consecutive_hard_failures = 0
        for _ in range(8):
            result = run_forward_sample(_BrokenClient(), db_path=db_path, write=True)
            assert result["outcome"] == "disk_low"
        assert sampler_mod._consecutive_hard_failures == 0

    assert not __import__("os").path.isfile(db_path)


def test_metrics_exposes_data_volume_gauges(monkeypatch):
    monkeypatch.setattr(
        "internal.disk_guard.disk_usage_for_metrics",
        lambda: _usage(free=111, used=222, total=333),
    )
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
        "internal.disk_guard.disk_usage_for_metrics",
        lambda: _usage(free=999, used=1, total=1000),
    )
    refresh_from_state()
    assert DATA_VOLUME_FREE_BYTES._value.get() == 999
    assert DATA_VOLUME_METRICS_OK._value.get() == 1

    monkeypatch.setattr("internal.disk_guard.disk_usage_for_metrics", lambda: None)
    refresh_from_state()
    assert DATA_VOLUME_FREE_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_USED_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_TOTAL_BYTES._value.get() == DATA_VOLUME_BYTES_UNAVAILABLE
    assert DATA_VOLUME_METRICS_OK._value.get() == 0
