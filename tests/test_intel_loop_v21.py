"""Focused v2.1 intel-loop checks — coverage, freshness, summer fallback, subnets meta."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.pump.desk_payload import attach_pump_freshness, _mark_stale
from internal.pump.routes import _summarize_ladder_payload
from internal.pump.state import coverage_meta
from server import _null_unfetched_metrics, app

client = TestClient(app)


def test_coverage_meta_unknown_feed_does_not_mark_all_missing():
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {"subnets": {"10": {"netuid": 10, "updated_at": fresh}}, "meta": {}}
    meta = coverage_meta(data, None)
    assert meta["coverage_known"] is False
    assert meta["missing_from_feed"] == []
    assert meta["feed_stalled"] is False


def test_split_v2_degraded_pump_alerts_stamp_freshness(monkeypatch):
    """Live split_v2 circuit-open path must not omit freshness (independent of /api/subnets timeout)."""
    import json

    import internal.worker_proxy as wp

    monkeypatch.setattr(wp, "_LAST_GOOD_PAYLOADS", {})
    response = wp._proxy_degraded_response("/api/pump-alerts")
    body = json.loads(response.body)
    assert body["status"] == "degraded"
    assert body["freshness"] == "stale"
    assert body["freshness_scope"] == "handler"
    assert body["data_available"] is False
    assert body.get("generated_at")


def test_timeout_with_rows_is_handler_stale_not_fresh():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out = attach_pump_freshness(
        {
            "status": "timeout",
            "alerts": [{"netuid": 1, "updated_at": now}],
        }
    )
    assert out["status"] == "timeout"
    assert out["freshness"] == "stale"
    assert out["freshness_scope"] == "handler"


def test_coverage_meta_flags_missing_and_stale_rows():
    stale = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat().replace("+00:00", "Z")
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "subnets": {
            "10": {"netuid": 10, "updated_at": fresh},
            "118": {"netuid": 118, "updated_at": stale},
        },
        "meta": {},
    }
    meta = coverage_meta(data, [10])
    assert meta["signal_row_count"] == 1
    assert 118 in meta["missing_from_feed"]
    assert meta["missing_from_feed_count"] == 1
    assert meta["feed_stalled"] is True
    assert meta["max_row_age_seconds"] is not None
    assert meta["max_row_age_seconds"] >= 6 * 3600
    assert meta["tracked_subnet_count"] == 2


def test_attach_pump_freshness_stale_rows_keep_success_status():
    old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat().replace("+00:00", "Z")
    payload = {
        "status": "success",
        "count": 1,
        "alerts": [{"netuid": 118, "updated_at": old, "timing": "confirmed"}],
    }
    out = attach_pump_freshness(payload)
    assert out["status"] == "success"
    assert out["freshness"] == "stale"
    assert out["freshness_scope"] == "rows"
    assert out["data_available"] is True
    assert out["max_row_age_seconds"] >= 6 * 3600
    assert out.get("generated_at")


def test_mark_stale_does_not_launder_without_freshness():
    out = _mark_stale({"status": "timeout", "alerts": []}, "2026-08-17T14:09:40Z")
    assert out["status"] == "ok"
    assert out["prior_status"] == "timeout"
    assert out["freshness"] == "stale"
    assert out["freshness_scope"] == "handler"
    assert out["stale"] is True


def test_listener_308_preserved():
    bounced = client.get("/listener", follow_redirects=False)
    assert bounced.status_code == 308
    assert bounced.headers.get("location") == "/subnetsummer"


def test_subnetsummer_fallback_when_context_fails():
    with patch(
        "internal.share_pages.routes._listener_page_context",
        side_effect=RuntimeError("context boom"),
    ):
        resp = client.get("/subnetsummer")
    assert resp.status_code == 200
    assert "degraded shell" in resp.text.lower() or "unable to render" in resp.text.lower()


def test_subnetsummer_fallback_when_render_fails():
    import internal.share_pages.routes as routes

    class _Boom:
        def TemplateResponse(self, *args, **kwargs):
            raise RuntimeError("render boom")

    with patch.object(routes, "templates", _Boom()):
        resp = client.get("/subnetsummer")
    assert resp.status_code == 200
    assert "unable to render" in resp.text.lower()


def test_subnets_meta_adds_handler_and_enrichment_fields():
    resp = client.get("/api/subnets?limit=1")
    assert resp.status_code == 200
    meta = (resp.json() or {}).get("meta") or {}
    assert "handler_status" in meta
    assert "enrichment_status" in meta
    assert "generated_at" in meta
    assert "data_available" in meta
    assert meta["handler_status"] in ("ok", "timeout")


def test_null_unfetched_metrics_does_not_paint_zero():
    out = _null_unfetched_metrics(
        {"emission": 0.0, "staking_data": {"total_stake": 0.0, "apy": 0}}
    )
    assert out["emission"] is None
    assert out["emission_available"] is False
    assert out["staking_data"]["total_stake"] is None
    assert out["staking_data"]["apy"] is None


def test_summarize_ladder_payload_strips_transitions():
    out = _summarize_ladder_payload(
        {
            "meta": {"signal_row_count": 1, "feed_stalled": False},
            "subnets": [
                {"netuid": 7, "phase": "STIRRING", "transitions": [{"from_phase": "DORMANT"}]}
            ],
        }
    )
    assert out["subnets"][0]["netuid"] == 7
    assert "transitions" not in out["subnets"][0]
    assert out["meta"]["signal_row_count"] == 1
