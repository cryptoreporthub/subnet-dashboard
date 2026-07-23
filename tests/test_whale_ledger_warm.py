"""Whale ledger warm — only scan netuids missing recent events."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from internal.whales import warm as warm_mod
from internal.whales.service import WhaleIntelligenceService
from internal.whales.warm import _netuids_missing_recent, ensure_whale_ledger_warm


def test_netuids_missing_recent_filters_covered():
    now = datetime.now(timezone.utc)
    events = [
        {
            "netuid": 6,
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "amount_tao": 100,
        },
        {
            "netuid": 2,
            "timestamp": (now - timedelta(hours=30)).isoformat(),
            "amount_tao": 500,
        },
    ]
    missing = _netuids_missing_recent(events, [6, 2, 97], hours=24.0)
    assert missing == [2, 97]


def test_ensure_warm_skips_without_taostats(monkeypatch):
    import fetchers.taostats_client as ts

    monkeypatch.setattr(ts, "is_available", lambda: False)
    warm_mod._last_warm_attempt = 0.0
    out = ensure_whale_ledger_warm([1, 2], force=True)
    assert out["status"] == "skipped"
    assert out["reason"] == "taostats_unavailable"


def test_ensure_warm_scans_only_missing(tmp_path, monkeypatch):
    import fetchers.taostats_client as ts
    import internal.whales.scanner as scanner_mod
    import internal.whales.service as svc_mod

    config = tmp_path / "whales.json"
    data = tmp_path / "intel.json"
    config.write_text(json.dumps({"min_tao_notional": 10.0}))
    data.write_text(json.dumps({"events": [], "profiles": {}, "open_positions": {}, "closed_trades": {}}))

    real = WhaleIntelligenceService(config_path=str(config), data_path=str(data))
    now = datetime.now(timezone.utc).isoformat()
    real.record_event(
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
        6,
        "buy",
        200.0,
        timestamp=now,
    )

    calls = []

    def capture_scan(netuids, subnet_meta_by_id=None, service=None):
        calls.append(list(netuids))
        return {"status": "success", "scanned": len(netuids), "ingested": 3, "subnets": []}

    class FakeSvc:
        def __init__(self, *a, **k):
            self.data = real.data

    monkeypatch.setattr(ts, "is_available", lambda: True)
    monkeypatch.setattr(scanner_mod, "scan_netuids", capture_scan)
    monkeypatch.setattr(svc_mod, "WhaleIntelligenceService", FakeSvc)
    warm_mod._last_warm_attempt = 0.0

    out = ensure_whale_ledger_warm([6, 97, 22], force=True)
    assert out["status"] == "ok"
    assert calls == [[97, 22]]
    assert out["ingested"] == 3


def test_scanner_parses_taostats_rao_and_nominator_dict(monkeypatch, tmp_path):
    from internal.whales.scanner import scan_subnet_delegations
    from internal.whales.service import WhaleIntelligenceService

    config = tmp_path / "whales.json"
    data = tmp_path / "intel.json"
    config.write_text(json.dumps({"min_tao_notional": 50.0}))
    data.write_text(json.dumps({"events": [], "profiles": {}, "open_positions": {}, "closed_trades": {}}))
    svc = WhaleIntelligenceService(config_path=str(config), data_path=str(data))

    monkeypatch.setattr(
        "fetchers.taostats_client.get_delegation_events",
        lambda **kwargs: {
            "data": [
                {
                    "nominator": {"ss58": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"},
                    "amount": "175000000000",  # 175 τ in rao
                    "action": "DELEGATE",
                    "slippage": "0.037",
                    "timestamp": "2026-07-23T12:00:00+00:00",
                    "extrinsic_id": "1-1",
                }
            ]
        },
    )
    result = scan_subnet_delegations(108, service=svc)
    assert result["rows_seen"] == 1
    assert result["ingested"] == 1
    ev = svc.data["events"][-1]
    assert ev["amount_tao"] == 175.0
    assert ev["side"] == "buy"
    assert ev["slippage_pct"] == 3.7


def test_kick_starts_background_warm(monkeypatch):
    from internal.whales.warm import kick_whale_ledger_warm
    import internal.whales.warm as warm_mod

    warm_mod._last_warm_attempt = 0.0
    called = []

    def fake_ensure(netuids, force=False, subnet_meta_by_id=None):
        called.append(list(netuids))
        return {"status": "ok"}

    monkeypatch.setattr(warm_mod, "ensure_whale_ledger_warm", fake_ensure)
    out = kick_whale_ledger_warm([6, 97], force=True)
    assert out["status"] == "started"
    # daemon thread should run quickly
    import time

    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    assert called and called[0] == [6, 97]