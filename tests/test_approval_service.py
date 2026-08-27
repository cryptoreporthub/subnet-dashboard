from datetime import datetime, timedelta, timezone

import pytest

from internal.approval.service import (
    ApprovalDenied,
    approve,
    enforce_approval,
    is_approved,
    reject,
    request_approval,
)


@pytest.fixture(autouse=True)
def _isolate_approval_store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "bot_approvals.json"))


def test_no_approval_means_no_mutation():
    record = request_approval(
        "recommend",
        "critical",
        evidence_refs=["pump_desk"],
        requested_by="mission_control",
        action_category="infrastructure",
    )
    assert record.status == "pending"
    assert is_approved(record.id) is False
    with pytest.raises(ApprovalDenied, match="no approval"):
        enforce_approval(record.id)


def test_human_approve_then_enforce_succeeds():
    record = request_approval("recommend", "critical", requested_by="mission_control")
    approved = approve(record.id, "designated_owner")
    assert approved.status == "approved"
    assert approved.approved_by == "designated_owner"
    assert is_approved(record.id) is True
    assert enforce_approval(record.id).id == record.id


def test_bot_cannot_approve_its_own_proposal():
    record = request_approval("recommend", "critical", requested_by="mission_control")
    with pytest.raises(ApprovalDenied, match="human"):
        approve(record.id, "mission_control")
    with pytest.raises(ApprovalDenied, match="human"):
        approve(record.id, "rogue_bot")
    assert is_approved(record.id) is False


def test_reject_blocks_enforcement():
    record = request_approval("recommend", "high", action_category="learning")
    reject(record.id, "learning_owner", "not yet")
    with pytest.raises(ApprovalDenied):
        enforce_approval(record.id)


def test_critical_expiry_is_one_hour():
    record = request_approval("recommend", "critical")
    requested = datetime.fromisoformat(record.requested_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
    assert timedelta(minutes=59) < (expires - requested) <= timedelta(hours=1)


def test_stale_freshness_expires_an_approved_record():
    record = request_approval(
        "recommend",
        "high",
        freshness={"status": "fresh", "sources": []},
    )
    approve(record.id, "designated_owner")
    from internal.approval import service as svc

    loaded = svc.get_record(record.id)
    assert loaded is not None
    loaded.freshness = {"status": "stale"}
    svc._put(loaded)
    assert is_approved(record.id) is False
    with pytest.raises(ApprovalDenied, match="expired"):
        enforce_approval(record.id)


def test_missing_record_fails_closed():
    with pytest.raises(ApprovalDenied, match="no approval"):
        enforce_approval("does-not-exist")


def test_wrong_role_cannot_approve():
    record = request_approval("recommend", "high", action_category="security")
    with pytest.raises(ApprovalDenied, match="role"):
        approve(record.id, "platform_operator")


def test_contract_shape_matches_bot_policy():
    record = request_approval(
        "recommend",
        "high",
        action_category="security",
        requested_by="mission_control",
    )
    contract = record.to_contract()
    assert set(contract) >= {
        "required",
        "status",
        "action_category",
        "approver_role",
        "surface",
        "approval_id",
    }
    assert contract["required"] is True
    assert contract["approval_id"] == record.id
    assert contract["action_category"] == "security"
    assert contract["approver_role"] == "security_operator"
