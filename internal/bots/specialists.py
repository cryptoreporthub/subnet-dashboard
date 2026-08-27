"""Minimum specialist adapters so Mission Control can route for real.

Dedicated bot modules (sentinel.py, market_desk.py, …) replace these when
present: each adapter looks for ``internal.bots.<name>.run`` first.
Adapters wrap existing evidence modules — they are not a second prediction
engine and they never mutate state.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional

from internal.ops.bot_policy import aggregate_freshness, bot_contract, classify_freshness

logger = logging.getLogger(__name__)

Specialist = Callable[[str, Mapping[str, Any]], Dict[str, Any]]

ADAPTER_NAMES = ("sentinel", "drift_qa", "proof_scout", "market_desk")


def _run_id() -> str:
    return str(uuid.uuid4())


def specialist_result(
    bot: str,
    *,
    summary: str,
    status: str = "ok",
    subject: Optional[str] = None,
    observations: Optional[List[Any]] = None,
    evidence: Optional[List[Any]] = None,
    unknowns: Optional[List[Any]] = None,
    recommended_action: Optional[str] = None,
    sources: Optional[List[Mapping[str, Any]]] = None,
    freshness: Optional[Mapping[str, Any]] = None,
    confidence: Optional[float] = None,
    action_category: Optional[str] = None,
    state_changing: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Shared specialist envelope from the evidence-bot contract."""
    contract = bot_contract(
        freshness=freshness,
        sources=sources,
        confidence=confidence,
        action_category=action_category,
        state_changing=state_changing,
    )
    payload: Dict[str, Any] = {
        "bot": bot,
        "run_id": _run_id(),
        "status": status,
        "subject": subject,
        "summary": summary,
        "observations": list(observations or []),
        "evidence": list(evidence or []),
        "unknowns": list(unknowns or []),
        "recommended_action": recommended_action,
        **contract,
    }
    if extra:
        payload.update(extra)
    return payload


def _failed(bot: str, error: str) -> Dict[str, Any]:
    return specialist_result(
        bot,
        summary=f"{bot} unavailable: {error}",
        status="degraded",
        unknowns=[error],
        sources=[classify_freshness("learning_health", degraded=True)],
        confidence=0.0,
    )


def _evidence_report() -> Dict[str, Any]:
    from internal.ops.evidence import build_evidence_report

    return build_evidence_report()


def run_sentinel(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Health observer backed by ``internal.ops.evidence``."""
    del query
    try:
        report = dict((context or {}).get("evidence_report") or _evidence_report())
    except Exception as exc:
        logger.warning("sentinel evidence read failed: %s", exc)
        return _failed("sentinel", str(exc))
    sources = list(report.get("evidence_sources") or [])
    alerts = list(report.get("alerts") or [])
    status = "ok" if report.get("status") == "ok" and not alerts else "degraded"
    summary = "ops evidence is healthy" if status == "ok" else (
        "ops evidence alerts: " + ", ".join(alerts) if alerts else "ops evidence is degraded"
    )
    return specialist_result(
        "sentinel",
        summary=summary,
        status=status,
        observations=alerts,
        evidence=[{"kind": "ops_evidence", "status": report.get("status")}],
        sources=sources,
        extra={"report_status": report.get("status"), "checked_at": report.get("checked_at")},
    )


def run_drift_qa(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Silent-failure observer: stale labeled live, degraded HTTP-shaped ok."""
    del query
    try:
        report = dict((context or {}).get("evidence_report") or _evidence_report())
    except Exception as exc:
        return _failed("drift_qa", str(exc))
    sources = list(report.get("evidence_sources") or [])
    freshness = aggregate_freshness(sources) if sources else classify_freshness("learning_health")
    flags: List[str] = []
    report_status = str(report.get("status") or "ok").lower()
    fresh_status = str(freshness.get("status") or "missing")
    if report_status in {"ok", "warn"} and fresh_status in {"stale", "missing", "degraded"}:
        flags.append("stale_data_labeled_live")
    if report_status == "ok" and fresh_status == "degraded":
        flags.append("http_200_contains_degraded_data")
    council = ((report.get("learning_outcomes") or {}) if isinstance(report.get("learning_outcomes"), dict) else {}).get("council_health") or {}
    if str(council.get("escalation") or "").upper() == "ALERT" and not report.get("alerts"):
        flags.append("learning_totals_disagree")
    status = "degraded" if flags else "ok"
    summary = "no drift flags" if not flags else "drift flags: " + ", ".join(flags)
    return specialist_result(
        "drift_qa",
        summary=summary,
        status=status,
        observations=flags,
        evidence=[{"freshness": fresh_status, "report_status": report_status}],
        sources=sources,
        extra={"flags": flags},
    )


def run_proof_scout(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Evidence bundle with population labels from ``internal.learning.evidence``."""
    from internal.learning.evidence import evidence_population, evidence_source

    try:
        report = dict((context or {}).get("evidence_report") or _evidence_report())
    except Exception as exc:
        return _failed("proof_scout", str(exc))
    subject = (context or {}).get("subject")
    pick = report.get("pick_audit") if isinstance(report.get("pick_audit"), dict) else {}
    row = {
        "pick_source": "council_pick",
        "archived": False,
        "verdict": pick.get("verdict"),
        "netuid": pick.get("published_netuid"),
    }
    supporting: List[Dict[str, Any]] = []
    contradictory: List[Dict[str, Any]] = []
    if pick.get("verdict") == "MISS":
        contradictory.append({"claim": "pick_audit MISS", "population": evidence_population(row)})
    elif pick.get("verdict"):
        supporting.append({"claim": f"pick_audit {pick.get('verdict')}", "population": evidence_population(row)})
    for alert in report.get("alerts") or []:
        contradictory.append({"claim": str(alert), "source": evidence_source(row)})
    if not supporting and not contradictory:
        supporting.append({"claim": "no contradictory ops alerts", "population": evidence_population(row)})
    status = "ok" if not contradictory else "degraded"
    summary = (
        f"evidence for {subject or query!r}: {len(supporting)} supporting, "
        f"{len(contradictory)} contradictory"
    )
    return specialist_result(
        "proof_scout",
        summary=summary,
        status=status,
        subject=subject,
        observations=[],
        evidence=supporting + contradictory,
        sources=list(report.get("evidence_sources") or []),
        extra={
            "supporting": supporting,
            "contradictory": contradictory,
            "source_attribution": {
                "ops_evidence": "internal/ops/evidence.py",
                "populations": "internal/learning/evidence.py",
            },
        },
    )


def run_market_desk(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Interpret existing Council/ops outputs. Does not pick or mutate."""
    try:
        report = dict((context or {}).get("evidence_report") or _evidence_report())
    except Exception as exc:
        return _failed("market_desk", str(exc))
    subject = (context or {}).get("subject")
    pump = report.get("pump_desk") if isinstance(report.get("pump_desk"), dict) else {}
    outcomes = report.get("learning_outcomes") if isinstance(report.get("learning_outcomes"), dict) else {}
    observation = f"pump_desk alert_level={pump.get('alert_level')!r}"
    interpretation = "no market interpretation beyond existing ops evidence"
    alert = str(pump.get("alert_level") or "").lower()
    if alert == "alert":
        interpretation = "pump desk is in alert; treat directional claims as degraded"
    elif outcomes.get("alert_level") == "alert":
        interpretation = "learning outcomes are in alert; do not promote a fresh pick"
    status = "degraded" if alert in {"alert", "warn"} or outcomes.get("alert_level") == "alert" else "ok"
    return specialist_result(
        "market_desk",
        summary=interpretation,
        status=status,
        subject=subject,
        observations=[observation, f"query={query!r}"],
        evidence=[{"pump_desk": pump, "learning_outcomes": {
            "alert_level": outcomes.get("alert_level"),
            "captured_at": outcomes.get("captured_at"),
        }}],
        sources=list(report.get("evidence_sources") or []),
        extra={"observation": observation, "interpretation": interpretation},
    )


_ADAPTERS: Dict[str, Specialist] = {
    "sentinel": run_sentinel,
    "drift_qa": run_drift_qa,
    "proof_scout": run_proof_scout,
    "market_desk": run_market_desk,
}


def resolve_specialist(name: str) -> Specialist:
    """Prefer a dedicated ``internal.bots.<name>.run`` if that module exists."""
    try:
        module = importlib.import_module(f"internal.bots.{name}")
        runner = getattr(module, "run", None)
        if callable(runner):
            return runner
    except Exception:
        pass
    if name in _ADAPTERS:
        return _ADAPTERS[name]
    raise KeyError(f"unknown specialist bot: {name}")
