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
    assert approval["risk_level"] == "critical"
    with pytest.raises(ApprovalDenied):
        gate_execution(approval["id"])
    approve(approval["id"], "platform_operator")
    assert enforce_approval(approval["id"]).status == "approved"


def test_read_only_monitor_does_not_request_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_STORE_PATH", str(tmp_path / "approvals.json"))
    mc = MissionControl(
        specialists={"sentinel": _bot("sentinel"), "drift_qa": _bot("drift_qa")}
    )
    response = mc.handle("The dashboard feels stale")
    assert response.intent == "monitor"
    assert response.risk_level == "low"
    assert response.approval_required is False
    assert response.merged_results["approval"] is None


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
    assert conflicts[0]["type"] == "status"

    mc = MissionControl(
        specialists={
            "market_desk": _bot("market_desk", status="ok", action="hold"),
            "proof_scout": _bot("proof_scout", status="degraded", action="restart"),
        }
    )
    response = mc.handle("Why is SN65 underperforming?")
    assert response.merged_results["contradictions"]
    assert response.merged_results["status"] == "degraded"
    assert "not averaged" in response.merged_results["summary"]


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
    assert response.merged_results["status"] == "degraded"
    assert "freshness" in response.merged_results["summary"]


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
