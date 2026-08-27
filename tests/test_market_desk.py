from datetime import datetime, timezone, timedelta
import json
import re
from unittest.mock import patch

from internal.bots.market_desk import analyze, report
from internal.ops.bot_policy import classify_freshness


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


def _fresh_snapshots(**overrides):
    snapshots = {
        "pump_state": {
            "meta": {"last_scan_at": _iso(timedelta(minutes=10))},
            "subnets": {
                "65": {
                    "netuid": 65,
                    "name": "TAOHash",
                    "phase": "ACCUMULATING",
                    "composite_score": 0.62,
                    "updated_at": _iso(timedelta(minutes=10)),
                    "transitions": [
                        {
                            "time": _iso(timedelta(minutes=12)),
                            "from_phase": "STIRRING",
                            "to_phase": "ACCUMULATING",
                            "composite_score": 0.41,
                            "signals": {
                                "volume_intensity": 0.7,
                                "momentum_1h": 0.03,
                                "price_change_24h": 0.05,
                            },
                        }
                    ],
                }
            },
        },
        "pump_desk": {
            "captured_at": _iso(timedelta(minutes=10)),
            "alert_level": "ok",
            "alerts": [{"netuid": 65, "name": "TAOHash", "badge": "BUILDING"}],
        },
        "signals": {
            "updated_at": _iso(timedelta(minutes=8)),
            "entries": [
                {
                    "subnet_id": 65,
                    "signal_type": "buy",
                    "timestamp": _iso(timedelta(minutes=8)),
                }
            ],
        },
        "live_subnet": {
            "netuid": 65,
            "name": "TAOHash",
            "price": 0.042,
            "price_change_24h": 0.05,
            "price_change_7d": 0.07,
        },
        "live_synced_at": _iso(timedelta(minutes=4)),
        "council_history": {
            "active": None,
            "history": [
                {
                    "netuid": 65,
                    "action": "long",
                    "outcome": "hit",
                    "resolved_at": _iso(timedelta(hours=6)),
                }
            ],
        },
        "score_snapshot": {
            "written_at": _iso(timedelta(minutes=12)),
            "day": [{"netuid": 65, "total_score": 0.71}],
        },
        "learning_outcomes": {
            "captured_at": _iso(timedelta(minutes=20)),
            "council_health": {"graded": 4, "correct": 2, "wrong": 2},
        },
        "predictions": {
            "resolved": [
                {
                    "netuid": 65,
                    "pick_source": "council",
                    "outcome": "hit",
                    "status": "resolved",
                    "resolved_at": _iso(timedelta(hours=6)),
                }
            ]
        },
        "message_intel": {
            "mode": "live",
            "last_message_at": _iso(timedelta(minutes=10)),
            "chatter": 0.4,
        },
    }
    snapshots.update(overrides)
    return snapshots


def _contract_keys(result):
    return {
        "bot",
        "run_id",
        "status",
        "subject",
        "summary",
        "observations",
        "evidence",
        "unknowns",
        "contradictions",
        "confidence",
        "freshness",
        "recommended_action",
        "approval_required",
        "approval",
        "audit",
    }.issubset(result)


def test_analyze_splits_observations_from_interpretations():
    result = analyze("SN65", now=NOW, snapshots=_fresh_snapshots())
    assert result["bot"] == "market_desk"
    assert result["subject"] == "SN65"
    assert _contract_keys(result)
    assert result["interpretations"]
    assert all(item["kind"] == "observation" for item in result["observations"])
    assert all(item["kind"] == "interpretation" for item in result["interpretations"])
    assert all(item["kind"] == "unknown" for item in result["unknowns"])
    observation_texts = " ".join(item["text"] for item in result["observations"]).lower()
    interpretation_texts = " ".join(item["text"] for item in result["interpretations"]).lower()
    assert "pump ladder phase is accumulating" in observation_texts
    assert "24h price change is 0.0500" in observation_texts
    assert "inference only" in interpretation_texts or "not a new council pick" in interpretation_texts
    assert "does not issue guaranteed" in result["summary"].lower()
    for item in result["observations"]:
        assert "inference only" not in item["text"].lower()
        assert "not a new council pick" not in item["text"].lower()


def test_claims_carry_source_specific_freshness():
    result = analyze("65", now=NOW, snapshots=_fresh_snapshots())
    assert result["observations"]
    for item in result["observations"]:
        freshness = item["freshness"]
        assert freshness["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
        assert "source" in freshness
        assert "age_seconds" in freshness
    populations = {item["population"] for item in result["evidence"]}
    assert "pump" in populations
    assert "council" in populations
    assert "learning" in populations
    assert "message_intel" in populations


def test_stale_source_cannot_yield_fresh_conclusion():
    snapshots = _fresh_snapshots(
        live_synced_at=_iso(timedelta(hours=3)),
        pump_state={
            "meta": {"last_scan_at": _iso(timedelta(hours=3))},
            "subnets": {
                "65": {
                    "netuid": 65,
                    "phase": "ACCUMULATING",
                    "composite_score": 0.62,
                    "updated_at": _iso(timedelta(hours=3)),
                    "transitions": [],
                }
            },
        },
        pump_desk={"captured_at": _iso(timedelta(hours=3))},
        signals={"updated_at": _iso(timedelta(hours=3)), "entries": []},
        score_snapshot={"written_at": _iso(timedelta(hours=5)), "day": []},
        learning_outcomes={"captured_at": _iso(timedelta(hours=5))},
        council_history={"active": None, "history": []},
        message_intel={"mode": "live", "last_message_at": _iso(timedelta(hours=3)), "chatter": 0},
    )
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    assert result["freshness"]["status"] != "fresh"
    assert result["status"] == "degraded"
    pump_env = classify_freshness("pump_desk", _iso(timedelta(hours=3)), now=NOW)
    assert pump_env["status"] == "stale"
    assert any(env["status"] == "stale" for env in result["freshness"]["sources"])


def test_archive_evidence_is_fresh_as_archive_but_not_authoritative():
    snapshots = _fresh_snapshots(
        predictions={
            "resolved": [
                {
                    "netuid": 65,
                    "archived": True,
                    "outcome": "hit",
                    "resolved_at": _iso(timedelta(hours=2)),
                }
            ]
        },
        message_intel={
            "mode": "archive",
            "last_message_at": _iso(timedelta(hours=2)),
            "chatter": 0.1,
        },
    )
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    archive = [
        item
        for item in result["evidence"]
        if item.get("population") == "archive" or item.get("claim_scope") == "historical"
    ]
    assert archive
    for item in archive:
        assert item["authoritative"] is False
        assert item["claim_scope"] == "historical"
        assert item["freshness"].get("mode") == "archive" or item["freshness"]["source"].endswith(
            "archive"
        )


def test_confidence_is_clamped_and_uncertainty_is_bounded():
    result = analyze("SN65", now=NOW, snapshots=_fresh_snapshots())
    assert result["confidence"] is not None
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["uncertainty"] is not None
    assert 0.0 <= result["uncertainty"]["low"] <= result["uncertainty"]["high"] <= 1.0
    with patch("internal.bots.market_desk._score_confidence", return_value=1.7):
        clamped = analyze("SN65", now=NOW, snapshots=_fresh_snapshots())
    assert clamped["confidence"] == 1.0
    with patch("internal.bots.market_desk._score_confidence", return_value=-0.4):
        floored = analyze("SN65", now=NOW, snapshots=_fresh_snapshots())
    assert floored["confidence"] == 0.0


def test_observational_only_run_has_null_confidence():
    snapshots = {
        "pump_state": {"subnets": {}},
        "live_subnet": {"netuid": 65, "price": 0.04},
        "live_synced_at": _iso(timedelta(minutes=3)),
    }
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    assert result["interpretations"] == []
    assert result["confidence"] is None
    assert result["uncertainty"] is None
    assert "observational only" in result["summary"].lower()


def test_comparison_signal_change_and_plain_language_summary():
    result = report("SN65", now=NOW, snapshots=_fresh_snapshots())
    assert result["comparison"]["current"]["phase"] == "ACCUMULATING"
    assert result["comparison"]["historical"]["phase"] == "STIRRING"
    assert result["comparison"]["deltas"]
    assert result["comparison"]["freshness"]["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
    assert result["signal_change"]["changed"] is True
    assert result["signal_change"]["from_phase"] == "STIRRING"
    assert result["signal_change"]["to_phase"] == "ACCUMULATING"
    assert result["signal_change"]["freshness"]["status"] in {"fresh", "aging", "stale", "missing", "degraded"}
    assert "volume_intensity" in " ".join(result["signal_change"]["drivers"])
    assert "council" in result["signal_change"]["explanation"].lower() or "learning" in result["signal_change"]["explanation"].lower()
    assert "SN65" in result["summary"]
    assert "observation" in result["summary"].lower()
    assert "does not override" in result["summary"].lower()


def test_analyze_is_read_only_and_approval_not_required():
    writes = []

    def _record_write(*args, **kwargs):
        writes.append((args, kwargs))
        raise AssertionError("Market Desk must not write")

    snapshots = _fresh_snapshots()
    with patch("internal.file_utils.safe_write_json", _record_write), patch(
        "internal.pump.state.save_state", _record_write
    ), patch(
        "internal.learning.predictions_store.save_predictions", _record_write
    ), patch(
        "internal.council.score_snapshots.save_score_snapshot", _record_write
    ):
        result = analyze("SN65", now=NOW, snapshots=snapshots)
        disk = analyze("SN65", now=NOW)
    assert writes == []
    assert result["audit"]["writes"] == []
    assert disk["audit"]["writes"] == []
    assert result["approval_required"] is False
    assert result["approval"]["required"] is False
    assert result["approval"]["status"] == "not_required"
    assert result["recommended_action"] is None


def test_empty_subject_is_blocked():
    result = analyze("", now=NOW, snapshots={})
    assert result["status"] == "blocked"
    assert result["approval"]["status"] == "not_required"
    assert result["freshness"]["status"] in {"missing", "degraded", "stale"}


def test_archive_freshness_does_not_make_current_claim_fresh():
    snapshots = {
        "predictions": {
            "resolved": [
                {
                    "netuid": 65,
                    "archived": True,
                    "outcome": "hit",
                    "resolved_at": _iso(timedelta(hours=1)),
                }
            ]
        },
        "message_intel": {
            "mode": "archive",
            "last_message_at": _iso(timedelta(hours=1)),
            "chatter": 0.2,
        },
    }
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    assert result["freshness"]["status"] != "fresh"
    assert result["comparison"]["freshness"]["status"] != "fresh"
    archive = [item for item in result["evidence"] if item.get("claim_scope") == "historical"]
    assert archive
    assert all(item["authoritative"] is False for item in archive)


def test_archived_council_row_is_not_a_live_learning_observation():
    snapshots = _fresh_snapshots(
        predictions={
            "resolved": [
                {
                    "netuid": 65,
                    "pick_source": "council",
                    "archived": True,
                    "outcome": "hit",
                    "resolved_at": _iso(timedelta(hours=2)),
                }
            ]
        }
    )
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    live_learning = [
        item
        for item in result["observations"]
        if item.get("population") == "learning" and item.get("metric") == "learning_row"
    ]
    archive_obs = [
        item for item in result["observations"] if item.get("population") == "archive"
    ]
    assert not live_learning
    assert archive_obs
    assert archive_obs[0]["freshness"]["authoritative"] is False
    assert archive_obs[0]["freshness"].get("claim_scope") == "historical"


def test_signal_row_uses_latest_timestamp():
    snapshots = _fresh_snapshots(
        signals={
            "updated_at": _iso(timedelta(minutes=2)),
            "entries": [
                {
                    "subnet_id": 65,
                    "signal_type": "sell",
                    "timestamp": _iso(timedelta(hours=5)),
                },
                {
                    "subnet_id": 65,
                    "signal_type": "buy",
                    "timestamp": _iso(timedelta(minutes=2)),
                },
            ],
        }
    )
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    signal_obs = [
        item
        for item in result["observations"]
        if item.get("population") == "signals" and item.get("metric") == "signal_type"
    ]
    assert signal_obs
    assert signal_obs[0]["value"] == "buy"


def test_signal_without_transition_stays_observational():
    snapshots = {
        "signals": {
            "updated_at": _iso(timedelta(minutes=3)),
            "entries": [
                {
                    "subnet_id": 65,
                    "signal_type": "buy",
                    "timestamp": _iso(timedelta(minutes=3)),
                }
            ],
        }
    }
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    assert result["signal_change"]["changed"] is False
    assert result["interpretations"] == []
    assert result["confidence"] is None
    assert result["uncertainty"] is None
    assert "observational only" in result["summary"].lower()


def test_disagreeing_sources_produce_visible_contradiction():
    snapshots = _fresh_snapshots(
        live_subnet={
            "netuid": 65,
            "name": "TAOHash",
            "price": 0.042,
            "price_change_24h": 0.08,
            "price_change_7d": 0.07,
        },
        pump_state={
            "meta": {"last_scan_at": _iso(timedelta(minutes=10))},
            "subnets": {
                "65": {
                    "netuid": 65,
                    "phase": "ACCUMULATING",
                    "composite_score": 0.62,
                    "updated_at": _iso(timedelta(minutes=10)),
                    "transitions": [
                        {
                            "time": _iso(timedelta(minutes=12)),
                            "from_phase": "STIRRING",
                            "to_phase": "ACCUMULATING",
                            "composite_score": 0.41,
                            "signals": {
                                "price_change_24h": -0.06,
                                "volume_intensity": 0.7,
                            },
                        }
                    ],
                }
            },
        },
        signals={
            "updated_at": _iso(timedelta(minutes=8)),
            "entries": [
                {
                    "subnet_id": 65,
                    "signal_type": "sell",
                    "timestamp": _iso(timedelta(minutes=8)),
                }
            ],
        },
    )
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    assert result["contradictions"]
    assert all(item["kind"] == "contradiction" for item in result["contradictions"])
    changes = [
        item["value"]
        for item in result["observations"]
        if item.get("metric") == "price_change_24h"
    ]
    assert 0.08 in changes
    assert -0.06 in changes
    assert 0.01 not in changes
    texts = " ".join(item["text"] for item in result["contradictions"]).lower()
    assert "disagrees" in texts or "direction" in texts
    assert "averaged" in texts or "blended" in texts or "kept" in texts
    assert "contradiction" in result["summary"].lower()


def test_missing_data_is_unknown_not_invented():
    snapshots = {
        "live_subnet": {"netuid": 65, "name": "TAOHash"},
        "live_synced_at": _iso(timedelta(minutes=3)),
        "pump_state": {
            "subnets": {
                "65": {
                    "netuid": 65,
                    "phase": "DORMANT",
                    "composite_score": None,
                    "updated_at": _iso(timedelta(minutes=3)),
                }
            }
        },
    }
    result = analyze("SN65", now=NOW, snapshots=snapshots)
    unknown_metrics = {item.get("metric") for item in result["unknowns"]}
    unknown_text = " ".join(item["text"] for item in result["unknowns"]).lower()
    assert "price_change_24h" in unknown_metrics
    assert "price" in unknown_metrics
    assert "composite_score" in unknown_metrics
    assert "unknown" in unknown_text
    assert "none was invented" in unknown_text
    invented = [
        item.get("value")
        for item in result["observations"]
        if item.get("metric") in {"price", "price_change_24h", "composite_score"}
    ]
    assert 0 not in invented and 0.0 not in invented
    assert all(item.get("kind") == "unknown" for item in result["unknowns"])


def test_report_never_emits_a_recommendation():
    advice = re.compile(
        r"\b(?:we recommend|recommended action|should buy|should sell|should hold|"
        r"buy now|sell now|hold this|trade advice)\b",
        re.I,
    )
    proposed = analyze(
        "SN65",
        now=NOW,
        snapshots=_fresh_snapshots(),
        proposed_action={
            "state_changing": True,
            "action": "restart worker",
            "action_category": "infrastructure",
        },
    )
    empty = analyze("SN65", now=NOW, snapshots={})
    for result in (proposed, empty):
        assert result["recommended_action"] is None
        assert result["approval_required"] is False
        assert result["approval"]["status"] == "not_required"
        blob = json.dumps(result)
        assert advice.search(blob) is None
        assert "restart worker" not in blob
        assert result["summary"].lower().count("recommend") <= 1
        assert "does not make a recommendation" in result["summary"].lower()


def test_categorical_specialist_disagreement_is_a_contradiction():
    def _run(council_action: str) -> dict:
        return analyze(
            "SN65",
            now=NOW,
            snapshots={
                "signals": {
                    "updated_at": _iso(timedelta(minutes=3)),
                    "entries": [
                        {
                            "subnet_id": 65,
                            "signal_type": "buy",
                            "timestamp": _iso(timedelta(minutes=3)),
                        }
                    ],
                },
                "council_history": {
                    "active": None,
                    "history": [
                        {
                            "netuid": 65,
                            "action": council_action,
                            "resolved_at": _iso(timedelta(hours=2)),
                        }
                    ],
                },
            },
        )

    for council_action in ("short", "reduce", "hold"):
        result = _run(council_action)
        assert result["contradictions"]
        texts = " ".join(item["text"] for item in result["contradictions"]).lower()
        assert "buy" in texts
        assert council_action in texts
        assert "blended" in texts or "kept" in texts
        obs = " ".join(item["text"] for item in result["observations"]).lower()
        assert "source field" in obs
        assert "not a market desk action" in obs
        values = {
            (item.get("population"), item.get("value"))
            for item in result["observations"]
            if item.get("metric") in {"signal_type", "council_history"}
        }
        assert ("signals", "buy") in values
        assert ("council", council_action) in values

