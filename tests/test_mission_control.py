import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from internal.approval.service import ApprovalDenied, approve, enforce_approval
from internal.bots.mission_control import (
    MissionControl,
    MissionControlResponse,
    assess_risk,
    classify_intent,
    detect_contradictions,
    enforce_freshness,
    gate_execution,
    handle,
    select_specialists,
)
from internal.bots.specialists import specialist_result
from internal.ops.bot_policy import classify_freshness


def _fresh_source(now=None):
    now = now or datetime.now(timezone.utc)
    return classify_freshness("pump_desk", now, now=now)


def _stale_source(now=None):
    now = now or datetime.now(timezone.utc)
    return classify_freshness("pump_desk", now - timedelta(hours=3), now=now)


def _bot(name, status="ok", summary=None, action=None, source=None):
    envelope = source if source is not None else _fresh_source()

    def run(query, context):
        return specialist_result(
            name,
            summary=summary or f"{name} ok",
            status=status,
            recommended_action=action,
            sources=[envelope],
            evidence=[{"kind": "fixture", "source": envelope.get("source")}],
            extra={"query": query, "subject": (context or {}).get("subject")},
        )

    return run


def test_intent_classification():
    assert classify_intent("The dashboard feels stale") == "monitor"
    assert classify_intent("Why is SN65 underperforming?") == "analyze"
    assert classify_intent("Is this signal trustworthy?") == "analyze"
    assert classify_intent("What is a HERO?") == "explain"
    assert classify_intent("Should we restart the worker?") == "recommend"
    assert classify_intent("Draft a release note") == "recommend"


def test_critical_risk_requires_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    assert assess_risk("restart the worker", "recommend") == "critical"
    assert assess_risk("Why is SN65 underperforming?", "analyze") == "medium"
    assert assess_risk("What is a HERO?", "explain") == "low"

    mc = MissionControl(specialists={"sentinel": _bot("sentinel"), "market_desk": _bot("market_desk"), "proof_scout": _bot("proof_scout")})
    response = mc.handle("Please restart the worker")
    assert isinstance(response, MissionControlResponse)
    assert response.intent == "recommend"
    assert response.risk_level == "critical"
    assert response.approval_required is True
    approval = response.merged_results["approval"]
    assert approval["status"] == "pending"
    assert approval["required"] is True
    assert approval["approval_id"]
    with pytest.raises(ApprovalDenied):
        gate_execution(approval["approval_id"])
    approve(approval["approval_id"], "platform_operator")
    assert enforce_approval(approval["approval_id"]).status == "approved"


def test_read_only_monitor_does_not_request_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    mc = MissionControl(
        specialists={"sentinel": _bot("sentinel"), "drift_qa": _bot("drift_qa")}
    )
    response = mc.handle("The dashboard feels stale")
    assert response.intent == "monitor"
    assert response.risk_level == "low"
    assert response.approval_required is False
    assert response.merged_results["approval"]["required"] is False
    assert response.merged_results["shareable"] is True
    assert response.merged_results["approval"]["status"] == "not_required"


def test_parallel_routing_runs_specialists_together(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    barrier = threading.Barrier(2)
    threads = []

    def make(name):
        def run(query, context):
            threads.append(threading.current_thread().ident)
            barrier.wait(timeout=2)
            time.sleep(0.05)
            return specialist_result(name, summary=name, sources=[_fresh_source()])

        return run

    mc = MissionControl(specialists={"sentinel": make("sentinel"), "drift_qa": make("drift_qa")})
    started = time.monotonic()
    response = mc.handle("monitor worker health")
    elapsed = time.monotonic() - started
    assert response.merged_results["routed_to"] == ["sentinel", "drift_qa"]
    assert set(response.merged_results["specialists"]) == {"sentinel", "drift_qa"}
    assert len(set(threads)) == 2
    assert elapsed < 1.0


def test_contradiction_detection_is_surfaced_not_averaged(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    conflicts = detect_contradictions(
        [
            specialist_result("sentinel", summary="healthy", status="ok", sources=[_fresh_source()]),
            specialist_result(
                "market_desk",
                summary="alert",
                status="degraded",
                recommended_action="restart",
                sources=[_fresh_source()],
            ),
        ]
    )
    assert conflicts
    assert conflicts[0]["tag"] == "status_disagreement"

    mc = MissionControl(
        specialists={
            "market_desk": _bot("market_desk", status="ok", action="hold"),
            "proof_scout": _bot("proof_scout", status="degraded", action="restart"),
        }
    )
    response = mc.handle("Why is SN65 underperforming?")
    assert response.merged_results["contradictions"]
    assert response.approval_required is True
    assert response.merged_results["shareable"] is False
    tags = {item["tag"] for item in response.merged_results["contradictions"]}
    from internal.ops.bot_policy import CONTRADICTION_TAGS

    assert tags <= set(CONTRADICTION_TAGS)
    assert "held pending" in response.merged_results["summary"]


def test_freshness_policy_degrades_stale_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    envelope = enforce_freshness([_stale_source()])
    assert envelope["status"] == "stale"
    assert envelope["claim_fresh"] is False
    assert envelope["enforced"] is True

    mc = MissionControl(
        specialists={
            "sentinel": _bot("sentinel", source=_stale_source()),
            "drift_qa": _bot("drift_qa", source=_stale_source()),
        }
    )
    response = mc.handle("The dashboard feels stale")
    assert response.merged_results["freshness"]["status"] == "stale"
    assert response.merged_results["freshness"]["claim_fresh"] is False
    assert response.merged_results["freshness"]["suspect_over_4h"] is False
    assert response.approval_required is True
    assert response.merged_results["shareable"] is False

    def lie(query, context):
        payload = specialist_result(
            "sentinel",
            summary="lying fresh",
            status="ok",
            sources=[_stale_source()],
        )
        payload["freshness"]["status"] = "stale"
        payload["freshness"]["claim_fresh"] = True
        return payload

    lying = MissionControl(specialists={"sentinel": lie, "drift_qa": _bot("drift_qa", source=_stale_source())})
    honest = lying.handle("The dashboard feels stale")
    nested = honest.merged_results["specialists"]["sentinel"]["freshness"]
    assert nested["status"] == "stale"
    assert nested["claim_fresh"] is False


def test_mission_control_response_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    mc = MissionControl(
        specialists={"market_desk": _bot("market_desk"), "proof_scout": _bot("proof_scout")}
    )
    response = mc.handle("Explain SN12 confidence")
    payload = response.to_dict()
    assert set(payload) == {"intent", "risk_level", "merged_results", "approval_required"}
    assert payload["intent"] in {"monitor", "analyze", "explain", "recommend"}
    assert payload["risk_level"] in {"low", "medium", "high", "critical"}
    assert isinstance(payload["merged_results"], dict)
    assert isinstance(payload["approval_required"], bool)
    assert payload["merged_results"]["subject"] == "SN12"
    assert select_specialists("monitor") == ["sentinel", "drift_qa"]
    assert "shield" in select_specialists("recommend", "restart the worker")
    for key in ("freshness", "confidence", "approval", "approval_required"):
        assert key in payload["merged_results"]


def test_handle_module_function_uses_real_adapters(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    report = {
        "status": "ok",
        "alerts": [],
        "checked_at": "2026-08-27T00:00:00Z",
        "evidence_sources": [_fresh_source()],
        "pick_audit": {"verdict": "HIT", "published_netuid": 12},
        "pump_desk": {"alert_level": None, "captured_at": "2026-08-27T00:00:00Z"},
        "learning_outcomes": {"alert_level": None, "captured_at": "2026-08-27T00:00:00Z"},
    }
    monkeypatch.setattr("internal.bots.specialists._evidence_report", lambda: report)
    response = handle("What is SN12?")
    assert isinstance(response, MissionControlResponse)
    assert response.intent == "explain"
    assert "market_desk" in response.merged_results["specialists"]
    assert "proof_scout" in response.merged_results["specialists"]
    assert response.approval_required is False
    assert response.merged_results["shareable"] is True
    assert response.merged_results["approval"]["approval_id"] is None


def test_insight_older_than_4h_is_suspect_even_if_source_policy_is_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    now = datetime.now(timezone.utc)
    # pick_audit fresh bound is 24h; 5h is still policy-fresh but >4h overlay.
    source = classify_freshness("pick_audit", now - timedelta(hours=5), now=now)
    assert source["status"] == "fresh"
    envelope = enforce_freshness([source])
    assert envelope["suspect_over_4h"] is True
    assert envelope["claim_fresh"] is False
    assert envelope["status"] == "aging"

    missing_age = {
        "source": "pick_audit",
        "status": "fresh",
        "captured_at": (now - timedelta(hours=5)).isoformat(),
        "age_seconds": None,
        "authoritative": True,
    }
    from_captured = enforce_freshness([missing_age])
    assert from_captured["suspect_over_4h"] is True
    assert from_captured["claim_fresh"] is False

    mc = MissionControl(
        specialists={"market_desk": _bot("market_desk", source=source), "proof_scout": _bot("proof_scout", source=source)}
    )
    response = mc.handle("Explain SN12 confidence")
    assert response.approval_required is True
    assert response.merged_results["freshness"]["suspect_over_4h"] is True


def test_high_risk_and_incomplete_go_through_approval_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    assert assess_risk("Draft a release note", "recommend") == "high"
    mc = MissionControl(
        specialists={
            "market_desk": _bot("market_desk"),
            "proof_scout": _bot("proof_scout"),
            "sentinel": _bot("sentinel"),
            "shield": _bot("shield"),
        }
    )
    response = mc.handle("Draft a release note")
    assert response.risk_level == "high"
    assert response.approval_required is True
    approval = response.merged_results["approval"]
    assert approval["required"] is True
    assert approval["status"] == "pending"
    assert approval["approval_id"]
    assert approval["approver_role"]
    assert approval["surface"]

    degraded = MissionControl(
        specialists={
            "sentinel": _bot("sentinel", status="degraded"),
            "drift_qa": _bot("drift_qa"),
        }
    )
    held = degraded.handle("The dashboard feels stale")
    assert held.approval_required is True
    assert held.merged_results["status"] == "incomplete"
    assert held.merged_results["shareable"] is False
    assert "sentinel" in held.merged_results["incomplete_specialists"]
    assert held.merged_results["claims"] == []


def test_notify_logs_routing_and_decision(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    caplog.set_level("INFO", logger="internal.ops.notify")
    mc = MissionControl(
        specialists={"sentinel": _bot("sentinel"), "drift_qa": _bot("drift_qa")}
    )
    mc.handle("The dashboard feels stale")
    events = [r.getMessage() for r in caplog.records if "mission_control" in r.getMessage()]
    assert any("mission_control.route" in msg for msg in events)
    assert any("mission_control.decision" in msg for msg in events)
