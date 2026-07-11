"""Phase C — decision lineage trace store (Agent B)."""

from __future__ import annotations

import json

import pytest

from internal.trace.engine import record_lineage
from internal.trace.store import get_record, list_records, load_store
from internal.trace.summary import summarize_trace


def test_record_lineage_persists_and_summarizes(tmp_path, monkeypatch):
    store_path = str(tmp_path / "decision_trace.json")
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(
        json.dumps(
            {
                "soul_map_state": {"learning_trail": []},
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul_path))

    record = record_lineage(
        decision_type="pick",
        decision={"action": "accumulate", "expert": "technical", "confidence": 0.82},
        signals=[
            {"type": "pump_phase", "payload": {"phase": "EARLY"}},
            {"type": "scenario_tag", "payload": {"regime": "volatile"}},
        ],
        subnet="Minos",
        netuid=1,
        store_path=store_path,
    )

    assert record["id"].startswith("tr_")
    stored = get_record(record["id"], path=store_path)
    assert stored is not None
    assert len(stored["signals"]) == 2

    summary = summarize_trace(load_store(path=store_path))
    assert "lineage store holds 1" in summary
    assert "pump_phase" in summary

    soul = json.loads(soul_path.read_text(encoding="utf-8"))
    lineage = soul["soul_map_state"]["decision_lineage"]
    assert lineage["total_records"] == 1
    assert lineage["last_record"]["id"] == record["id"]

    trail = soul["soul_map_state"]["learning_trail"]
    assert any(
        e.get("event_type") in {"conviction_update", "signal_triggered"}
        for e in trail
    )


def test_trace_api_list_and_record(tmp_path, monkeypatch):
    store_path = str(tmp_path / "decision_trace.json")
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(
        json.dumps({"soul_map_state": {"learning_trail": []}, "adversarial_state": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.trace.store.TRACE_STORE_PATH", store_path)
    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul_path))

    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        empty = client.get("/api/trace/list")
        assert empty.status_code == 200
        assert empty.json()["count"] == 0

        post = client.post(
            "/api/trace/record",
            json={
                "decision_type": "weight_change",
                "decision": {"expert": "quant", "delta": 0.02},
                "signals": [{"type": "soul_map_disposition", "payload": {"action": "accumulate"}}],
                "subnet": "Alpha",
                "netuid": 3,
            },
        )
        assert post.status_code == 200
        body = post.json()
        assert body["status"] == "success"
        trace_id = body["record"]["id"]

        listed = client.get("/api/trace/list")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert "summary" in listed.json()

        detail = client.get(f"/api/trace/{trace_id}")
        assert detail.status_code == 200
        assert detail.json()["record"]["id"] == trace_id

        summary = client.get("/api/trace/summary")
        assert summary.status_code == 200
        assert len(summary.json()["text"]) > 20


def test_summarize_trace_empty_store():
    text = summarize_trace({"meta": {}, "records": []})
    assert "empty" in text.lower()
