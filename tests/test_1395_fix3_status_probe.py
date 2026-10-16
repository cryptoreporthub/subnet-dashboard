"""#1395 Fix 3 — status RPC probe + recorder_state cooldown visibility."""

from __future__ import annotations

from unittest.mock import patch

import internal.integrations.status as st
from internal.chain_client import ChainClient, _RL_LOCK, _RL_STEP, _RL_UNTIL, note_rate_limit
from internal.chain_price.reader import ChainReader, reset_shared_reader
from internal.chain_price.scheduler import recorder_state
from internal.integrations.status import build_integrations_status, clear_status_cache


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
        with patch.object(st, "_BITTENSOR_RPC", bm):
            with patch.object(st, "_rpc_chain_healthy", side_effect=_count):
                with patch.object(st, "_http_probe", return_value=(True, 200, "ok")):
                    build_integrations_status(force=True)
    assert calls.count(bm) == 1


def test_recorder_state_reports_provider_cooldown_after_rate_limit():
    client = ChainClient("https://finney.example/rpc", init_volume_db=False)
    reader = ChainReader([("finney", client)])
    reset_shared_reader()
    reader.provider_served = "finney"
    with patch("internal.chain_price.scheduler.get_shared_reader", return_value=reader):
        ep = client.endpoint
        with _RL_LOCK:
            _RL_UNTIL.clear()
            _RL_STEP.clear()
        clock = [500.0]
        with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
            note_rate_limit(ep)
            state = recorder_state()
    assert state["provider_served"] == "finney"
    finney_row = next(p for p in state["providers"] if p["label"] == "finney")
    assert finney_row["cooldown_remaining_s"] >= 60.0
