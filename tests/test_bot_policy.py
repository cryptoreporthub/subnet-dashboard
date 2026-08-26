from datetime import datetime, timezone, timedelta

from internal.ops.bot_policy import (
    APPROVAL_POLICY,
    aggregate_freshness,
    approval_for,
    bot_contract,
    classify_freshness,
)


def test_source_thresholds_cover_all_required_states():
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    assert classify_freshness(
        "pump_desk", now - timedelta(seconds=1200), now=now
    )["status"] == "fresh"
    assert classify_freshness(
        "pump_desk", now - timedelta(seconds=1201), now=now
    )["status"] == "aging"
    assert classify_freshness(
        "pump_desk", now - timedelta(seconds=3601), now=now
    )["status"] == "stale"
    assert classify_freshness("pump_desk")["status"] == "missing"
    assert classify_freshness("pump_desk", now, degraded=True)["status"] == "degraded"


def test_archive_message_evidence_is_not_authoritative_for_live_claims():
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    envelope = classify_freshness(
        "message_intel_archive",
        now - timedelta(hours=1),
        now=now,
        mode="archive",
        authoritative=False,
    )
    assert envelope["status"] == "fresh"
    assert envelope["mode"] == "archive"
    assert envelope["authoritative"] is False


def test_aggregate_freshness_keeps_worst_source_visible():
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    sources = [
        classify_freshness("worker_heartbeat", now, now=now),
        classify_freshness(
            "pump_desk", now - timedelta(seconds=3601), now=now
        ),
    ]
    result = aggregate_freshness(sources)
    assert result["status"] == "stale"
    assert len(result["sources"]) == 2


def test_state_changing_actions_have_role_and_pending_approval():
    for category, rule in APPROVAL_POLICY.items():
        approval = approval_for(category, state_changing=True)
        assert approval["required"] is True
        assert approval["status"] == "pending"
        assert approval["approver_role"] == rule["approver_role"]
        assert approval["surface"] == rule["surface"]

    read_only = bot_contract(source="learning_health", confidence=1.5)
    assert read_only["approval_required"] is False
    assert read_only["approval"]["status"] == "not_required"
    assert read_only["confidence"] == 1.0

    proposed = bot_contract(
        source="worker_heartbeat",
        captured_at="2026-08-26T00:00:00Z",
        action_category="infrastructure",
        state_changing=True,
    )
    assert proposed["approval_required"] is True
    assert proposed["approval"]["status"] == "pending"
    assert proposed["approval"]["approver_role"] == "platform_operator"

    unknown = approval_for("unclassified_action", state_changing=True)
    assert unknown["required"] is True
    assert unknown["approver_role"] == "designated_owner"