"""#1395 Fix 3 — status RPC probe + recorder_state cooldown visibility."""

from __future__ import annotations

import json
import logging
import time
from unittest.mock import patch

import internal.integrations.status as st
import requests
from fastapi.testclient import TestClient
from internal.chain_client import ChainClient, _RL_LOCK, _RL_STEP, _RL_UNTIL, _metric_endpoint, note_rate_limit
from internal.chain_price.reader import ChainReader, reset_shared_reader
from internal.chain_price.scheduler import recorder_state
from internal.integrations.status import build_integrations_status, clear_status_cache
from server import app

_REVIEW_SECRET = "FAKE_REVIEW_KEY_1427"
_KEYED_RPC = f"http://127.0.0.1:1/rpc?api_key={_REVIEW_SECRET}"


def setup_function():
    clear_status_cache()
    reset_shared_reader()


def test_bittensor_probe_uses_finney_when_finney_rpc_url_set(monkeypatch):
    finney = "https://entrypoint-finney.opentensor.ai"
    monkeypatch.setenv("FINNEY_RPC_URL", finney)
    monkeypatch.delenv("BITTENSOR_RPC_URL", raising=False)
    seen: list[str] = []

    def _track(endpoint: str):
        seen.append(endpoint.rstrip("/"))
        return True, "chain RPC ok"

    with patch.object(st, "_rpc_chain_healthy", side_effect=_track):
        with patch.object(st, "_http_probe", return_value=(True, 200, "ok")):
            payload = build_integrations_status(force=True)
    finney_row = next(r for r in payload["integrations"] if r["slug"] == "bittensor")
    assert finney in seen
    assert "via Finney RPC" in finney_row["detail"]


def test_status_single_rpc_post_when_bittensor_and_blockmachine_share_url(monkeypatch):
    bm = "https://rpc.blockmachine.io"
    monkeypatch.delenv("FINNEY_RPC_URL", raising=False)
    monkeypatch.delenv("BITTENSOR_RPC_URL", raising=False)
    monkeypatch.setenv("BLOCKMACHINE_RPC_URL", bm)
    calls: list[str] = []

    def _count(endpoint: str):
        calls.append(endpoint.rstrip("/"))
        return True, "chain RPC ok"

    with patch.object(st, "_BLOCKMACHINE_RPC", bm):
        with patch.object(st, "_bittensor_rpc_url", return_value=bm):
            with patch.object(st, "_rpc_chain_healthy", side_effect=_count):
                with patch.object(st, "_http_probe", return_value=(True, 200, "ok")):
                    build_integrations_status(force=True)
    assert calls.count(bm) == 1


def test_status_single_rpc_post_concurrent_slow_shared_url(monkeypatch):
    """Must single-flight: parallel probes cannot each POST before memo is set."""
    bm = "https://rpc.blockmachine.io"
    monkeypatch.delenv("FINNEY_RPC_URL", raising=False)
    monkeypatch.delenv("BITTENSOR_RPC_URL", raising=False)
    calls: list[str] = []

    def _slow(endpoint: str):
        calls.append(endpoint.rstrip("/"))
        time.sleep(0.3)
        return True, "chain RPC ok"

    with patch.object(st, "_BLOCKMACHINE_RPC", bm):
        with patch.object(st, "_bittensor_rpc_url", return_value=bm):
            with patch.object(st, "_rpc_chain_healthy", side_effect=_slow):
                with patch.object(st, "_http_probe", return_value=(True, 200, "ok")):
                    build_integrations_status(force=True)
    assert len(calls) == 1


def test_metric_endpoint_never_returns_raw_untrusted_url():
    assert _metric_endpoint(_KEYED_RPC) == "127.0.0.1"
    assert _REVIEW_SECRET not in _metric_endpoint(_KEYED_RPC)
    assert _metric_endpoint("/rpc?api_key=leak") == "unknown"
    assert "api_key" not in _metric_endpoint(":///path?api_key=leak")
    assert _metric_endpoint(None) == "unknown"
    assert _metric_endpoint("http://[bad?k=leak") == "unknown"
    assert _metric_endpoint("http://[::1/bracket") == "unknown"


def test_rpc_chain_healthy_bad_url_returns_tuple_not_raise():
    ok, detail = st._rpc_chain_healthy("http://[bad?k=leak")
    assert ok is False
    assert isinstance(detail, str)
    assert "http://" not in detail


def test_recorder_state_bad_finney_rpc_url_hostname_unknown(monkeypatch):
    monkeypatch.setenv("FINNEY_RPC_URL", "http://[::1/bracket?api_key=leak")
    monkeypatch.delenv("BITTENSOR_RPC_URL", raising=False)
    reset_shared_reader()
    state = recorder_state()
    finney = next(p for p in state["providers"] if p["label"] == "finney")
    assert finney["hostname"] == "unknown"
    assert "api_key" not in str(state)


def test_subnet_integrations_never_leaks_rpc_credentials(monkeypatch, caplog):
    monkeypatch.setenv("BITTENSOR_RPC_URL", _KEYED_RPC)
    monkeypatch.delenv("FINNEY_RPC_URL", raising=False)

    def _fail_post(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError(
            f"Connection refused for {_KEYED_RPC}"
        )

    with caplog.at_level(logging.DEBUG, logger="internal.integrations.status"):
        with patch.object(st._get_probe_session(), "post", side_effect=_fail_post):
            with patch.object(st, "_http_probe", return_value=(True, 200, "ok")):
                with TestClient(app) as client:
                    resp = client.get("/api/subnet-integrations")
    assert resp.status_code == 200
    raw = json.dumps(resp.json())
    assert _REVIEW_SECRET not in raw
    assert _KEYED_RPC not in raw
    for record in caplog.records:
        msg = record.getMessage()
        assert _REVIEW_SECRET not in msg
        assert _KEYED_RPC not in msg


def test_recorder_state_reports_provider_cooldown_after_rate_limit():
    client = ChainClient("https://finney.example/rpc", init_volume_db=False)
    reader = ChainReader([("finney", client)])
    reset_shared_reader()
    with patch("internal.chain_price.scheduler.get_shared_reader", return_value=reader):
        ep = client.endpoint
        with _RL_LOCK:
            _RL_UNTIL.clear()
            _RL_STEP.clear()
        clock = [500.0]
        with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
            note_rate_limit(ep)
            state = recorder_state()
    assert "provider_served" not in state
    finney_row = next(p for p in state["providers"] if p["label"] == "finney")
    assert finney_row["cooldown_remaining_s"] >= 60.0
