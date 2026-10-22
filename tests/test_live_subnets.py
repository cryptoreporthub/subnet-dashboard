"""Live subnets cache path + worker bootstrap."""

import json
import logging
import pickle
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


def _fetch_rows(result):
    if isinstance(result, dict):
        return result.get("rows") or []
    return result or []


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
    monkeypatch.setenv("WORKER_HEAVY", "full")

    from internal import live_subnets

    monkeypatch.setattr(live_subnets, "AUTO_SYNC", True)
    monkeypatch.setattr(live_subnets, "_in_ci_or_test", False)

    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_sync_once", return_value=True) as sync,
    ):
        assert live_subnets.bootstrap_live_subnets_cache() is True
    sync.assert_called_once()


def test_bootstrap_defers_until_registry_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_SUBNETS_BOOT_IMMEDIATE", "on")
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "full")
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

    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=[{"netuid": 1, "price": 1.0}]),
    ):
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



def test_sync_failed_snapshot_not_recorded_as_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal import live_subnets

    fetch = {
        "rows": [],
        "degraded_reason": "membership_unavailable",
        "refresh_complete": False,
        "netuid_outcomes": {},
    }
    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=fetch),
    ):
        assert live_subnets._sync_once() is False

    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["reason"] == "failed:membership_unavailable"
    assert status.get("unavailable") is True


def test_sync_normal_path_records_boot_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal import live_subnets

    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=[{"netuid": 1, "price": 1.0}]),
    ):
        assert live_subnets._sync_once() is True

    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["ok"] is True
    assert status["rows"] > 0


def test_registry_netuids_from_committed_registry():
    from internal import live_subnets

    if not os.path.isfile(live_subnets.REGISTRY_PATH):
        pytest.skip("config/registry.json not present (gitignored local fallback)")
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

    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", side_effect=slow_fetch),
    ):
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

    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": n, "price": 1.0} for n in range(1, 130)]),
    )
    out = live_subnets._fetch_chain_data()
    rows = _fetch_rows(out)
    assert rows and len(rows) >= 100 and rows[0]["netuid"] == 1
    assert isinstance(out, dict) and out.get("refresh_complete") is True


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


def test_fetch_chain_data_falls_back_to_registry_on_get_netuids_exception(monkeypatch, tmp_path):
    """Verify _fetch_chain_data falls back to _registry_netuids when get_netuids raises."""
    from internal import live_subnets

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 42, "price": 1.0}]),
    )

    with (
        patch("internal.subnet_universe.get_netuids", side_effect=RuntimeError("Snapshot corrupt")),
        patch("internal.live_subnets_fetch_child._registry_netuids", return_value=[42]),
    ):
        out = live_subnets._fetch_chain_data()

    assert _fetch_rows(out) and _fetch_rows(out)[0]["netuid"] == 42


def test_fetch_hung_child_killed_second_sync_proceeds(monkeypatch, caplog, tmp_path):
    """Hung chain fetch must be killed within budget; no orphan fetch thread; retry works."""
    from internal import live_subnets

    caplog.set_level(logging.WARNING, logger="live_subnets")
    counter = tmp_path / "fetch_calls"
    counter.write_text("0", encoding="utf-8")
    hang = threading.Event()
    hang.set()
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 0.25)

    def _slow_snapshot(_deadline):
        n = int(counter.read_text(encoding="utf-8")) + 1
        counter.write_text(str(n), encoding="utf-8")
        if n == 1:
            hang.clear()
            hang.wait(timeout=30)
        return LiveSubnetSnapshot(
            block_hash="0xblock",
            provider="finney",
            rows=[{"netuid": 1, "price": 1.0, "source": "finney"}],
            netuid_outcomes={1: "ok"},
            requested_netuids=[1],
            membership_resolved=True,
        )

    from internal.chain_price.live_subnet_snapshot import LiveSubnetSnapshot

    try:
        with (
            patch(
                "internal.chain_price.live_subnet_snapshot.fetch_live_subnet_snapshot",
                _slow_snapshot,
            ),
            patch("internal.subnet_universe.get_netuids", return_value=[1]),
        ):
            first = live_subnets._fetch_chain_data()
            assert first is None
            assert int(counter.read_text(encoding="utf-8")) == 1
            fetch_threads = [
                t
                for t in threading.enumerate()
                if t.name == "live-subnets-fetch" and t.is_alive()
            ]
            assert fetch_threads == []

            second = live_subnets._fetch_chain_data()
            assert _fetch_rows(second) and _fetch_rows(second)[0]["netuid"] == 1
            assert int(counter.read_text(encoding="utf-8")) == 2

        assert any("RPC budget exceeded" in r.message for r in caplog.records)
    finally:
        hang.set()


def test_child_logs_payload_too_large(monkeypatch, caplog):
    from internal.live_subnets_fetch_child import _send_child_frame
    import socket

    caplog.set_level(logging.WARNING, logger="live_subnets_fetch_child")
    monkeypatch.setattr("internal.live_subnets_ipc._MAX_PAYLOAD", 64)
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    huge = {"ok": True, "data": [{"netuid": i, "price": float(i)} for i in range(200)]}
    assert (
        _send_child_frame(left, huge, deadline=time.monotonic() + 2.0) is False
    )
    assert any("payload" in r.message and "exceeds" in r.message for r in caplog.records)


def test_child_logs_pickle_failed(monkeypatch, caplog):
    from internal.live_subnets_fetch_child import _send_child_frame
    import socket

    caplog.set_level(logging.WARNING, logger="live_subnets_fetch_child")

    class _Bad:
        def __reduce__(self):
            raise RuntimeError("nope")

    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    assert _send_child_frame(left, {"ok": True, "bad": _Bad()}, deadline=time.monotonic() + 2.0) is False
    assert any("pickle failed" in r.message for r in caplog.records)


def test_parent_logs_child_closed_not_timeout_on_send_fail(monkeypatch, caplog):
    from internal import live_subnets
    import internal.live_subnets_ipc as ipc

    caplog.set_level(logging.WARNING, logger="live_subnets")
    real_framed = ipc.send_framed_body

    def _fail_result(conn, body, *, deadline=None):
        try:
            msg = pickle.loads(body)
            if isinstance(msg, dict) and msg.get("ok") and "data" in msg:
                return False
        except Exception:
            pass
        return real_framed(conn, body, deadline=deadline)

    monkeypatch.setattr(ipc, "send_framed_body", _fail_result)
    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 1, "price": 1.0}]),
    )
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "5.0")

    assert live_subnets._fetch_chain_data() is None
    assert any("closed before result" in r.message for r in caplog.records)
    assert not any("RPC budget exceeded" in r.message for r in caplog.records)


def test_child_result_send_failure_returns_none(monkeypatch):
    from internal import live_subnets
    import internal.live_subnets_ipc as ipc

    real_framed = ipc.send_framed_body

    def _fail_result(conn, body, *, deadline=None):
        try:
            msg = pickle.loads(body)
            if isinstance(msg, dict) and msg.get("ok") and "data" in msg:
                return False
        except Exception:
            pass
        return real_framed(conn, body, deadline=deadline)

    monkeypatch.setattr(ipc, "send_framed_body", _fail_result)
    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 1, "price": 1.0}]),
    )
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "2.0")

    assert live_subnets._fetch_chain_data() is None


def test_parent_sends_rpc_deadline_monotonic_after_ready(monkeypatch):
    """Child batch clock must match parent RPC window (not a fresh 85s after setup)."""
    from internal import live_subnets
    import internal.live_subnets_ipc as ipc

    sent_deadlines: list[float] = []
    real_send = ipc.send_message

    def _spy_send(conn, payload, *, deadline=None):
        if isinstance(payload, dict) and "rpc_deadline_monotonic" in payload:
            sent_deadlines.append(float(payload["rpc_deadline_monotonic"]))
        return real_send(conn, payload, deadline=deadline)

    monkeypatch.setattr(ipc, "send_message", _spy_send)
    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 1, "price": 1.0}]),
    )
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_SETUP_SLEEP_SECONDS", "0.25")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 1.0)

    t0 = time.monotonic()
    out = live_subnets._fetch_chain_data()
    assert _fetch_rows(out) and _fetch_rows(out)[0]["netuid"] == 1
    assert len(sent_deadlines) == 1
    assert sent_deadlines[0] > t0
    assert sent_deadlines[0] <= t0 + 1.05


def test_parent_recv_gets_partial_rows_within_rpc_margin(monkeypatch):
    """Partial snapshot fetch still returns rows within parent RPC margin."""
    from internal import live_subnets
    from internal.chain_price.live_subnet_snapshot import LiveSubnetSnapshot

    def _fake_snapshot(_deadline):
        return LiveSubnetSnapshot(
            block_hash="0xblock",
            provider="finney",
            rows=[{"netuid": 1, "name": "SN1", "price": 1.0, "source": "finney"}],
            netuid_outcomes={1: "ok", 2: "batch_expired"},
            batch_expired=True,
            requested_netuids=[1, 2],
            membership_resolved=True,
        )

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv("LIVE_SUBNETS_RPC_RETURN_MARGIN_SECONDS", "0.35")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "1.1")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 1.1)

    t0 = time.monotonic()
    with (
        patch(
            "internal.chain_price.live_subnet_snapshot.fetch_live_subnet_snapshot",
            _fake_snapshot,
        ),
        patch("internal.subnet_universe.get_netuids", return_value=[2, 1]),
    ):
        out = live_subnets._fetch_chain_data()
    elapsed = time.monotonic() - t0

    assert out is not None
    assert [r["netuid"] for r in _fetch_rows(out)] == [1]
    assert out.get("refresh_complete") is False
    assert out.get("missing_netuids") == [2]
    assert out.get("degraded_reason") == "batch_deadline"
    assert out.get("batch_expired") is True
    assert out.get("netuid_outcomes", {}).get(2) == "batch_expired"
    assert elapsed < 1.05


def test_fetch_chain_data_carries_netuid_outcomes_on_no_price(monkeypatch):
    from internal import live_subnets
    from internal.chain_price.live_subnet_snapshot import LiveSubnetSnapshot

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setenv("LIVE_SUBNETS_RPC_RETURN_MARGIN_SECONDS", "0.35")
    monkeypatch.setenv("LIVE_SUBNETS_TEST_REQUESTED_NETUIDS", json.dumps([2, 1]))

    def _fake_snapshot(_deadline):
        return LiveSubnetSnapshot(
            block_hash="0xblock",
            provider="finney",
            rows=[{"netuid": 1, "name": "SN1", "price": 1.0, "source": "finney"}],
            netuid_outcomes={1: "ok", 2: "no_price"},
            batch_expired=False,
            requested_netuids=[1, 2],
            membership_resolved=True,
        )

    with patch(
        "internal.chain_price.live_subnet_snapshot.fetch_live_subnet_snapshot",
        _fake_snapshot,
    ):
        out = live_subnets._fetch_chain_data()
    assert out is not None
    assert out.get("degraded_reason") == "fetch_errors"
    assert out.get("netuid_outcomes", {}).get(2) == "no_price"
    assert out.get("batch_expired") is False


def test_fetch_logs_timing_when_spawn_grace_exceeded(caplog, monkeypatch):
    from internal import live_subnets

    caplog.set_level(logging.INFO, logger="live_subnets")
    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "fork")
    monkeypatch.setenv("LIVE_SUBNETS_SPAWN_GRACE_SECONDS", "0.001")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 1.0)
    assert live_subnets._fetch_chain_data() is None
    assert any("live_subnets fetch timing" in r.message for r in caplog.records)


def test_ready_sleep_uses_spawn_grace_not_rpc_budget(monkeypatch):
    from internal import live_subnets

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "spawn")
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_READY_SLEEP_SECONDS", "0.35")
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "0")
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 1, "price": 1.0}]),
    )
    monkeypatch.setenv("LIVE_SUBNETS_SPAWN_GRACE_SECONDS", "0.1")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "2")
    assert live_subnets._fetch_chain_data() is None

    monkeypatch.delenv("LIVE_SUBNETS_CHILD_READY_SLEEP_SECONDS", raising=False)
    monkeypatch.setenv("LIVE_SUBNETS_SPAWN_GRACE_SECONDS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "0.35")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "0.1")
    assert live_subnets._fetch_chain_data() is None

    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "2")
    out = live_subnets._fetch_chain_data()
    assert _fetch_rows(out) and _fetch_rows(out)[0]["netuid"] == 1


def test_killed_child_does_not_return_partial_rows(monkeypatch):
    from internal import live_subnets

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "spawn")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "30")
    out = live_subnets._fetch_chain_data()
    assert out is None


def test_fetch_hung_child_killed_second_sync_proceeds_spawn(monkeypatch, caplog):
    """Spawn child cannot inherit fork monkeypatches; env sleep must still be killable."""
    import multiprocessing

    from internal import live_subnets

    caplog.set_level(logging.WARNING, logger="live_subnets")
    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "spawn")
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "30")

    first = live_subnets._fetch_chain_data()
    assert first is None
    assert not any(p.is_alive() for p in multiprocessing.active_children())

    monkeypatch.delenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", raising=False)
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 1, "price": 1.0}]),
    )
    second = live_subnets._fetch_chain_data()
    assert _fetch_rows(second) and _fetch_rows(second)[0]["netuid"] == 1
    assert any("RPC budget exceeded" in r.message for r in caplog.records)


def test_heartbeat_updates_during_hung_chain_fetch(monkeypatch, tmp_path):
    from internal import live_subnets
    from internal import worker_heartbeat

    counter = tmp_path / "fetch_calls"
    counter.write_text("0", encoding="utf-8")
    hang = threading.Event()
    hang.set()
    hb_path = tmp_path / "hb.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(hb_path))
    monkeypatch.setenv("LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setenv("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "30")

    timestamps = []

    def _beat():
        for _ in range(6):
            worker_heartbeat.touch_heartbeat()
            raw = worker_heartbeat.read_heartbeat()
            if raw:
                timestamps.append(raw["ts"])
            time.sleep(0.05)

    try:
        with patch("internal.subnet_universe.get_netuids", return_value=[1]):
            fetch_t = threading.Thread(target=live_subnets._fetch_chain_data, name="fetch-parent")
            beat_t = threading.Thread(target=_beat, name="heartbeat-test")
            fetch_t.start()
            beat_t.start()
            time.sleep(0.35)
            hang.set()
            fetch_t.join(timeout=5)
            beat_t.join(timeout=2)
            assert fetch_t.is_alive() is False
    finally:
        hang.set()

    assert len(timestamps) >= 3
    assert len(set(timestamps)) >= 2
    assert worker_heartbeat.is_alive(max_age_seconds=5)


def test_fetch_chain_data_spawn_context_trivial(monkeypatch):
    """Prod uses spawn; force spawn under pytest with env-driven fake child rows."""
    from internal import live_subnets

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "spawn")
    monkeypatch.setenv(
        "LIVE_SUBNETS_TEST_ROWS_JSON",
        json.dumps([{"netuid": 7, "price": 2.0}]),
    )
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 5.0)
    out = live_subnets._fetch_chain_data()
    assert _fetch_rows(out) and _fetch_rows(out)[0]["netuid"] == 7


def test_sync_lock_blocks_parallel_fetch_across_threads(monkeypatch, tmp_path):
    """_sync_lock guarantees at most one in-flight sync (and thus one fetch child)."""
    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    started = threading.Event()
    release = threading.Event()
    fetch_calls = {"n": 0}

    def slow_fetch():
        fetch_calls["n"] += 1
        started.set()
        release.wait(timeout=5)
        return [{"netuid": 1, "price": 1.0}]

    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", side_effect=slow_fetch),
    ):
        threads = [threading.Thread(target=live_subnets._sync_once) for _ in range(3)]
        for t in threads:
            t.start()
        assert started.wait(timeout=2)
        for t in threads:
            t.join(timeout=2)
        release.set()
        for t in threads:
            t.join(timeout=5)

    assert fetch_calls["n"] == 1


def test_large_test_rows_pipe_carries_registry_sized_payload(monkeypatch, tmp_path):
    """Prod-scale row count must round-trip through the fetch Pipe."""
    import json

    from internal import live_subnets

    monkeypatch.setenv("LIVE_SUBNETS_MP_CONTEXT", "spawn")
    monkeypatch.setattr(live_subnets, "SYNC_TIMEOUT_SECONDS", 30.0)
    netuids = list(range(1, 129))  # prod-scale row count without committed registry.json
    template = {
        "price": 1.234,
        "stake": 1000.0,
        "total_stake": 2000.0,
        "emission": 0.5,
        "liquidity": 3000.0,
        "total_tao": 4000.0,
        "total_alpha": 5000.0,
        "root_prop": 0.01,
        "buys_24hr": 12,
        "sells_24hr": 8,
        "buy_volume_24h": 100.0,
        "sell_volume_24h": 80.0,
    }
    rows = [{"netuid": n, **template} for n in netuids]
    payload_bytes = len(json.dumps(rows).encode("utf-8"))
    assert payload_bytes < 8 * 1024 * 1024  # ponytail: pipe smoke; prod sample recorded in handoff

    monkeypatch.setenv("LIVE_SUBNETS_TEST_ROWS_JSON", json.dumps(rows))
    out = live_subnets._fetch_chain_data()
    assert out is not None
    assert len(_fetch_rows(out)) == len(netuids)
    (tmp_path / "pipe_size.json").write_text(json.dumps({"bytes": payload_bytes, "rows": len(rows)}))


def test_sync_once_partial_fetch_records_incomplete(monkeypatch, tmp_path):
    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    partial = {
        "rows": [{"netuid": 1, "price": 1.0}],
        "requested_netuids": [1, 2],
        "completed_netuids": [1],
        "missing_netuids": [2],
        "refresh_complete": False,
        "degraded_reason": "fetch_errors",
        "batch_expired": False,
        "netuid_outcomes": {1: "ok", 2: "rpc_error"},
    }
    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=partial),
    ):
        assert live_subnets._sync_once() is False

    cache = json.loads((tmp_path / "live_subnets.json").read_text(encoding="utf-8"))
    assert cache["live_row_count"] == 1
    assert cache["refresh_complete"] is False
    assert cache["missing_netuids"] == [2]
    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["ok"] is False
    assert status["refresh_complete"] is False
    assert status["reason"] == "fetch_errors"


def test_sync_once_batch_deadline_reason_when_batch_expired(monkeypatch, tmp_path):
    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    partial = {
        "rows": [{"netuid": 1, "price": 1.0}],
        "requested_netuids": [1, 2],
        "completed_netuids": [1],
        "missing_netuids": [2],
        "refresh_complete": False,
        "degraded_reason": "batch_deadline",
        "batch_expired": True,
        "netuid_outcomes": {1: "ok", 2: "batch_expired"},
    }
    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=partial),
    ):
        live_subnets._sync_once()
    status = json.loads((tmp_path / "live_subnets_boot.json").read_text())
    assert status["reason"] == "batch_deadline"


def test_sync_once_complete_fetch_control(monkeypatch, tmp_path):
    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    complete = {
        "rows": [{"netuid": 1, "price": 1.0}, {"netuid": 2, "price": 2.0}],
        "requested_netuids": [1, 2],
        "completed_netuids": [1, 2],
        "missing_netuids": [],
        "refresh_complete": True,
        "degraded_reason": None,
    }
    with (
        patch.object(live_subnets, "registry_ready", return_value=True),
        patch.object(live_subnets, "_fetch_chain_data", return_value=complete),
    ):
        assert live_subnets._sync_once() is True

    cache = json.loads((tmp_path / "live_subnets.json").read_text(encoding="utf-8"))
    assert cache["refresh_complete"] is True
    assert cache["live_row_count"] == 2


def test_live_data_freshness_partial_does_not_force_stale(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    now = datetime.now(timezone.utc).isoformat()
    cache = tmp_path / "live_subnets.json"
    cache.write_text(
        json.dumps(
            {
                "synced_at": now,
                "count": 5,
                "live_row_count": 1,
                "refresh_complete": False,
                "missing_netuids": [2],
                "degraded_reason": "batch_deadline",
                "subnets": [{"netuid": 1}],
            }
        ),
        encoding="utf-8",
    )
    with patch("internal.data_volume.worker_data_freshness", return_value=None):
        info = live_subnets.live_data_freshness()
    assert info["stale"] is False
    assert info["refresh_complete"] is False
    assert info["live_row_count"] == 1
    assert info["subnet_count"] == 5
    assert info["missing_netuids"] == [2]


def test_live_data_freshness_marks_stale_when_sync_disabled(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    from internal import live_subnets

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(live_subnets, "AUTO_SYNC", False)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cache = tmp_path / "live_subnets.json"
    cache.write_text(
        json.dumps({"synced_at": old, "count": 1, "subnets": [{"netuid": 1}]}),
        encoding="utf-8",
    )
    with patch("internal.data_volume.worker_data_freshness", return_value=None):
        info = live_subnets.live_data_freshness()
    assert info["sync_enabled"] is False
    assert info["stale"] is True
