"""Live subnets cache path + worker bootstrap."""

import json
import threading
from unittest.mock import patch

import pytest


def test_cache_path_respects_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "vol"))
    from internal import live_subnets

    assert live_subnets._cache_path() == str(tmp_path / "vol" / "live_subnets.json")


def test_bootstrap_noop_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "on")
    monkeypatch.setenv("RUN_MODE", "worker")
    from internal import live_subnets

    assert live_subnets.bootstrap_live_subnets_cache() is False


def test_bootstrap_calls_sync_once_on_worker(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "on")
    monkeypatch.setenv("RUN_MODE", "worker")

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)

    with patch.object(live_subnets, "_sync_once", return_value=True) as sync:
        assert live_subnets.bootstrap_live_subnets_cache() is True
    sync.assert_called_once()


def test_bootstrap_defers_until_registry_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "on")
    monkeypatch.setenv("RUN_MODE", "worker")
    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    monkeypatch.setattr(live_subnets, "_registry_netuids", lambda: [])
    with (
        patch("internal.subnet_universe.get_netuids", return_value=[]),
        patch.object(live_subnets, "_sync_once") as sync,
    ):
        assert live_subnets.bootstrap_live_subnets_cache() is False
    sync.assert_not_called()
    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["reason"] == "registry_not_ready"


def test_bootstrap_skipped_when_immediate_off(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "off")
    monkeypatch.setenv("RUN_MODE", "web")

    from internal import live_subnets

    with patch.object(live_subnets, "_sync_once") as sync:
        assert live_subnets.bootstrap_live_subnets_cache() is False
    sync.assert_not_called()


def test_bootstrap_skipped_on_worker_when_immediate_off(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "off")
    monkeypatch.setenv("RUN_MODE", "worker")

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)
    with patch.object(live_subnets, "_sync_once", return_value=True) as sync:
        assert live_subnets.bootstrap_live_subnets_cache() is False
    sync.assert_not_called()


def test_sync_writes_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_SUBNETS_AUTO_SYNC", "true")

    from internal import live_subnets

    with patch.object(live_subnets, "_fetch_chain_data", return_value=[{"netuid": 1, "price": 1.0}]):
        assert live_subnets._sync_once() is True

    cache_file = tmp_path / "live_subnets.json"
    assert cache_file.is_file()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data.get("count", 0) >= 1


def test_sync_empty_registry_has_distinct_boot_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal import live_subnets

    with (
        patch.object(live_subnets, "_registry_netuids", return_value=[]),
        patch("internal.subnet_universe.get_netuids", return_value=[]),
        patch.object(live_subnets, "_fetch_chain_data", return_value=[]),
    ):
        assert live_subnets._sync_once() is False

    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["reason"] == "registry_not_ready"
    assert status["ok"] is False


def test_sync_normal_path_records_boot_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal import live_subnets

    with patch.object(live_subnets, "_fetch_chain_data", return_value=[{"netuid": 1, "price": 1.0}]):
        assert live_subnets._sync_once() is True

    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["ok"] is True
    assert status["rows"] > 0


def test_registry_netuids_from_committed_registry():
    from internal import live_subnets

    ids = live_subnets._registry_netuids()
    assert len(ids) >= 100
    assert 1 in ids


def test_sync_once_skips_concurrent_call(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal import live_subnets

    started = threading.Event()
    release = threading.Event()
    fetch_count = {"n": 0}

    def slow_fetch():
        fetch_count["n"] += 1
        started.set()
        release.wait(timeout=5)
        return [{"netuid": 1, "price": 1.0}]

    with patch.object(live_subnets, "_fetch_chain_data", side_effect=slow_fetch):
        t1 = threading.Thread(target=live_subnets._sync_once)
        t2 = threading.Thread(target=live_subnets._sync_once)
        t1.start()
        assert started.wait(timeout=2)
        t2.start()
        t2.join(timeout=2)
        release.set()
        t1.join(timeout=5)

    assert fetch_count["n"] == 1


def test_fetch_chain_data_passes_registry_netuids(monkeypatch):
    from internal import live_subnets

    seen = {}

    class _Client:
        def get_subnet_price_rows(self, netuids):
            seen["netuids"] = netuids
            return [{"netuid": 1, "price": 1.0}]

        def get_all_subnet_data(self, netuids=None):
            seen["full"] = netuids
            return []

    monkeypatch.setenv("LIVE_SUBNETS_FETCH_MODE", "lite")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 5.0)
    with patch("internal.chain_client.get_default_client", return_value=_Client()):
        out = live_subnets._fetch_chain_data()
    assert out and out[0]["netuid"] == 1
    assert seen["netuids"] and len(seen["netuids"]) >= 100


# ---------------------------------------------------------------------------
# Slice A: Comprehensive registry_ready alignment coverage
# ---------------------------------------------------------------------------


def test_registry_ready_universe_snapshot_only():
    """Verify Slice A: universe snapshot populated alone satisfies readiness."""
    from internal.live_subnets import registry_ready
    with (
        patch("internal.live_subnets._registry_netuids", return_value=[]),
        patch("internal.subnet_universe.get_netuids", return_value=[1, 2, 3]),
    ):
        assert registry_ready() is True


def test_registry_ready_registry_fallback_only():
    """Verify Slice A: registry populated alone satisfies readiness if universe empty."""
    from internal.live_subnets import registry_ready
    with (
        patch("internal.live_subnets._registry_netuids", return_value=[4, 5]),
        patch("internal.subnet_universe.get_netuids", return_value=[]),
    ):
        assert registry_ready() is True


def test_registry_ready_both_empty_defers():
    """Verify Slice A: when both sources are empty, registry_ready defers (False)."""
    from internal.live_subnets import registry_ready
    with (
        patch("internal.live_subnets._registry_netuids", return_value=[]),
        patch("internal.subnet_universe.get_netuids", return_value=[]),
    ):
        assert registry_ready() is False


def test_registry_ready_handles_get_netuids_exception():
    """Verify Slice A: exception in get_netuids gracefully falls back to registry."""
    from internal.live_subnets import registry_ready
    with (
        patch("internal.subnet_universe.get_netuids", side_effect=RuntimeError("Snapshot read failed")),
        patch("internal.live_subnets._registry_netuids", return_value=[7]),
    ):
        assert registry_ready() is True
