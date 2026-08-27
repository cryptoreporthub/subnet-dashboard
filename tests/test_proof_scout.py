from __future__ import annotations

from datetime import datetime, timedelta, timezone

from internal.bots.proof_scout import EvidenceBundle, gather_evidence, parse_subnet_id
from internal.learning.evidence import SOURCE_POPULATIONS
from internal.ops.bot_policy import FRESHNESS_THRESHOLDS


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def test_parse_subnet_id_accepts_sn_prefix():
    assert parse_subnet_id(65) == 65
    assert parse_subnet_id("SN65") == 65
    assert parse_subnet_id("sn-12") == 12
    assert parse_subnet_id("nope") is None


def test_gather_evidence_classifies_support_contradiction_and_populations(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "c1",
                "netuid": 65,
                "pick_source": "council",
                "direction": "up",
                "created_at": _iso(timedelta(hours=12)),
            }
        ],
        "resolved": [
            {
                "id": "s1",
                "netuid": 65,
                "shadow": True,
                "direction": "down",
                "correct": True,
                "created_at": _iso(timedelta(minutes=30)),
                "resolved_at": _iso(timedelta(minutes=10)),
            },
            {
                "id": "p1",
                "netuid": 65,
                "pick_source": "pump_lead",
                "pump_badge": "BUILDING",
                "direction": "up",
                "created_at": _iso(timedelta(minutes=10)),
            },
            {
                "id": "a1",
                "netuid": 65,
                "archived": True,
                "direction": "up",
                "created_at": _iso(timedelta(hours=2)),
            },
            {
                "id": "u1",
                "netuid": 65,
                "created_at": _iso(timedelta(minutes=5)),
            },
            {
                "id": "other",
                "netuid": 8,
                "pick_source": "council",
                "direction": "up",
                "created_at": _iso(timedelta(minutes=1)),
            },
        ],
    }
    ops_report = {
        "status": "ok",
        "checked_at": _iso(timedelta(0)),
        "paths": {"pump_desk": None, "pick_audit": None},
        "pick_audit": {"published_netuid": 65, "verdict": "HIT", "action": "LONG"},
        "evidence_sources": [
            {
                "source": "pick_audit",
                "captured_at": _iso(timedelta(hours=3)),
                "status": "fresh",
            }
        ],
    }
    monkeypatch.setattr("internal.bots.proof_scout.load_predictions", lambda **_kwargs: ledger)
    monkeypatch.setattr("internal.bots.proof_scout.build_evidence_report", lambda: ops_report)
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda netuid: None,
    )

    original_shadow = dict(ledger["resolved"][0])
    bundle = gather_evidence(65, claim="LONG", now=NOW)
    payload = bundle.to_dict()

    assert isinstance(bundle, EvidenceBundle)
    assert payload["bot"] == "proof_scout"
    assert payload["subnet_id"] == 65
    assert payload["subject"] == "SN65"
    assert payload["approval_required"] is False
    assert payload["approval"]["status"] == "not_required"
    assert set(payload["populations"]) == set(SOURCE_POPULATIONS)
    assert payload["populations"]["council"] >= 1
    assert payload["populations"]["shadow"] == 1
    assert payload["populations"]["pump"] == 1
    assert payload["populations"]["archive"] == 1
    assert payload["populations"]["unknown"] == 1
    assert "ops.evidence" in payload["audit"]["sources_read"]
    assert "learning.predictions" in payload["audit"]["sources_read"]
    assert payload["confidence"] is not None
    assert all(item["population"] in SOURCE_POPULATIONS for item in payload["evidence"])
    assert all(item["attribution"]["module"] for item in payload["evidence"])
    assert all("captured_at" in item["attribution"] for item in payload["evidence"])
    assert ledger["resolved"][0] == original_shadow
    assert "evidence_source" not in original_shadow

    by_id = {item["payload"].get("id"): item for item in payload["evidence"]}
    assert by_id["c1"]["relation"] == "supporting"
    assert by_id["c1"]["population"] == "council"
    assert by_id["s1"]["relation"] == "contradictory"
    assert by_id["s1"]["population"] == "shadow"
    assert by_id["p1"]["population"] == "pump"
    assert by_id["a1"]["population"] == "archive"
    assert by_id["a1"]["freshness"]["authoritative"] is False
    assert by_id["a1"]["freshness"]["mode"] == "archive"
    assert by_id["u1"]["population"] == "unknown"
    assert by_id["u1"]["freshness"]["status"] == "missing"
    assert by_id["u1"]["freshness"]["authoritative"] is False
    assert "other" not in by_id

    # Policy §2: council uses pick_audit (fresh ≤24h); 12h old is still fresh.
    assert by_id["c1"]["freshness"]["source"] == "pick_audit"
    assert by_id["c1"]["freshness"]["status"] == "fresh"
    assert by_id["c1"]["freshness"]["thresholds_seconds"] == FRESHNESS_THRESHOLDS["pick_audit"]
    # Policy §2: pump uses pump_desk (fresh ≤20m); 10m old is fresh.
    assert by_id["p1"]["freshness"]["source"] == "pump_desk"
    assert by_id["p1"]["freshness"]["status"] == "fresh"


def test_policy_section_2_pump_aging_threshold(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "p_aging",
                "netuid": 12,
                "pick_source": "pump_lead",
                "direction": "up",
                "created_at": _iso(timedelta(seconds=1201)),
            }
        ],
        "resolved": [],
    }
    monkeypatch.setattr("internal.bots.proof_scout.load_predictions", lambda **_kwargs: ledger)
    monkeypatch.setattr(
        "internal.bots.proof_scout.build_evidence_report",
        lambda: {"status": "ok", "paths": {}, "pick_audit": {}, "evidence_sources": []},
    )
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda netuid: None,
    )
    bundle = gather_evidence("SN12", claim="LONG", now=NOW)
    item = bundle.to_dict()["evidence"][0]
    assert item["freshness"]["source"] == "pump_desk"
    assert item["freshness"]["status"] == "aging"
    assert item["freshness"]["thresholds_seconds"]["fresh"] == 1200
    assert item["freshness"]["thresholds_seconds"]["aging"] == 3600


def test_stale_authoritative_evidence_degrades_bundle(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "old_council",
                "netuid": 3,
                "pick_source": "council",
                "direction": "up",
                "created_at": _iso(timedelta(days=8)),
            }
        ],
        "resolved": [],
    }
    monkeypatch.setattr("internal.bots.proof_scout.load_predictions", lambda **_kwargs: ledger)
    monkeypatch.setattr(
        "internal.bots.proof_scout.build_evidence_report",
        lambda: {"status": "ok", "paths": {}, "pick_audit": {}, "evidence_sources": []},
    )
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda netuid: None,
    )
    bundle = gather_evidence(3, claim="LONG", now=NOW)
    assert bundle.to_dict()["evidence"][0]["freshness"]["status"] == "stale"
    assert bundle.status == "degraded"


def test_read_path_does_not_persist_prediction_migrations(monkeypatch):
    calls = []

    def _load(*, persist=True):
        calls.append(persist)
        return {"predictions": [], "resolved": []}

    monkeypatch.setattr("internal.bots.proof_scout.load_predictions", _load)
    monkeypatch.setattr(
        "internal.bots.proof_scout.build_evidence_report",
        lambda: {"status": "ok", "paths": {}, "pick_audit": {}, "evidence_sources": []},
    )
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda netuid: None,
    )
    gather_evidence(1, now=NOW)
    assert calls == [False]


def test_invalid_subnet_is_degraded_and_read_only(monkeypatch):
    monkeypatch.setattr(
        "internal.bots.proof_scout.load_predictions",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not load")),
    )
    bundle = gather_evidence("not-a-subnet", now=NOW)
    assert bundle.status == "degraded"
    assert bundle.approval_required is False
    assert "invalid subnet_id" in bundle.unknowns
