from __future__ import annotations

from datetime import datetime, timedelta, timezone

from internal.bots.proof_scout import (
    EvidenceBundle,
    SCOUT_FRESHNESS_BUCKETS,
    gather_evidence,
    parse_subnet_id,
)
from internal.learning.evidence import SOURCE_POPULATIONS
from internal.ops.bot_policy import FRESHNESS_THRESHOLDS


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def _patch_sources(monkeypatch, ledger, ops_report=None):
    monkeypatch.setattr("internal.bots.proof_scout.load_predictions", lambda **_kwargs: ledger)
    monkeypatch.setattr(
        "internal.bots.proof_scout.build_evidence_report",
        lambda: ops_report
        or {"status": "ok", "paths": {}, "pick_audit": {}, "evidence_sources": []},
    )
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda netuid: None,
    )


def test_parse_subnet_id_accepts_sn_prefix():
    assert parse_subnet_id(65) == 65
    assert parse_subnet_id("SN65") == 65
    assert parse_subnet_id("sn-12") == 12
    assert parse_subnet_id("nope") is None


def test_gather_evidence_classifies_thesis_without_concluding(monkeypatch):
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
    _patch_sources(monkeypatch, ledger, ops_report)
    original_shadow = dict(ledger["resolved"][0])
    bundle = gather_evidence(65, "LONG", now=NOW)
    payload = bundle.to_dict()

    assert isinstance(bundle, EvidenceBundle)
    assert payload["bot"] == "proof_scout"
    assert payload["subnet_id"] == 65
    assert payload["thesis"] == "LONG"
    assert "claim" not in payload
    assert "summary" not in payload
    assert "confidence" not in payload
    assert "recommended_action" not in payload
    assert payload["approval_required"] is False
    assert set(payload["populations"]) == set(SOURCE_POPULATIONS)
    assert payload["populations"]["council"] >= 1
    assert payload["populations"]["shadow"] == 1
    assert payload["populations"]["pump"] == 1
    assert payload["populations"]["archive"] == 1
    assert payload["populations"]["unknown"] == 1
    assert payload["freshness"]["buckets"] == list(SCOUT_FRESHNESS_BUCKETS)
    assert "ops.evidence" in payload["audit"]["sources_read"]
    assert "learning.predictions" in payload["audit"]["sources_read"]
    assert ledger["resolved"][0] == original_shadow

    by_id = {item["payload"].get("id"): item for item in payload["evidence"]}
    assert by_id["c1"]["relation"] == "supporting"
    assert by_id["c1"]["population"] == "council"
    assert by_id["s1"]["relation"] == "contradictory"
    assert by_id["s1"]["population"] == "shadow"
    assert by_id["p1"]["population"] == "pump"
    assert by_id["a1"]["population"] == "archive"
    assert by_id["a1"]["freshness"]["authoritative"] is False
    assert by_id["u1"]["population"] == "unknown"
    assert by_id["u1"]["freshness"]["status"] == "missing"
    assert by_id["u1"]["freshness"]["source"] == "unknown"
    assert by_id["u1"]["freshness"]["thresholds_seconds"] == {}
    assert "other" not in by_id
    assert by_id["c1"]["freshness"]["status"] == "fresh"
    assert by_id["c1"]["freshness"]["thresholds_seconds"] == FRESHNESS_THRESHOLDS["pick_audit"]
    assert by_id["p1"]["freshness"]["source"] == "pump_desk"
    assert by_id["p1"]["freshness"]["status"] == "fresh"

    flag_pairs = {tuple(flag["populations"]) for flag in payload["contradiction_flags"]}
    assert ("council", "shadow") in flag_pairs or ("shadow", "council") in flag_pairs
    assert all(flag["kind"] == "cross_source" for flag in payload["contradiction_flags"])


def test_thesis_is_not_inferred(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "c1",
                "netuid": 7,
                "pick_source": "council",
                "direction": "up",
                "created_at": _iso(timedelta(minutes=1)),
            }
        ],
        "resolved": [],
    }
    _patch_sources(monkeypatch, ledger)
    bundle = gather_evidence(7, now=NOW)
    payload = bundle.to_dict()
    assert payload["thesis"] is None
    assert payload["evidence"][0]["relation"] == "observation"
    assert payload["supporting"] == []
    assert payload["contradictory"] == []


def test_policy_section_2_aging_cutoff_is_stale(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "p_stale",
                "netuid": 12,
                "pick_source": "pump_lead",
                "direction": "up",
                "created_at": _iso(timedelta(seconds=1201)),
            }
        ],
        "resolved": [],
    }
    _patch_sources(monkeypatch, ledger)
    item = gather_evidence(12, "LONG", now=NOW).to_dict()["evidence"][0]
    assert item["freshness"]["source"] == "pump_desk"
    assert item["freshness"]["status"] == "stale"
    assert item["freshness"]["thresholds_seconds"]["fresh"] == 1200
    assert item["freshness"]["thresholds_seconds"]["aging"] == 3600


def test_policy_section_2_past_aging_is_expired(monkeypatch):
    ledger = {
        "predictions": [
            {
                "id": "p_expired",
                "netuid": 12,
                "pick_source": "pump_lead",
                "direction": "up",
                "created_at": _iso(timedelta(seconds=3601)),
            }
        ],
        "resolved": [],
    }
    _patch_sources(monkeypatch, ledger)
    bundle = gather_evidence(12, "LONG", now=NOW)
    item = bundle.to_dict()["evidence"][0]
    assert item["freshness"]["status"] == "expired"
    assert bundle.status == "ok"
    assert bundle.freshness["counts"]["expired"] == 1


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
    assert bundle.thesis is None
    assert "invalid subnet_id" in bundle.unknowns
    assert bundle.contradiction_flags == ()
