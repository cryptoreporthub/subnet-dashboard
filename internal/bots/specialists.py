"""Minimum specialist adapters so Mission Control can route for real.

Dedicated bot modules (sentinel.py, market_desk.py, …) replace these when
present: ``resolve_specialist`` prefers ``run(query, context)``, then wraps
``observe(snapshot)`` (Drift/QA), then these adapters.
Adapters wrap existing evidence modules — they are not a second prediction
engine and they never mutate state.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import logging
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from internal.ops.bot_policy import aggregate_freshness, bot_contract, classify_freshness

logger = logging.getLogger(__name__)

Specialist = Callable[[str, Mapping[str, Any]], Dict[str, Any]]

ADAPTER_NAMES = ("sentinel", "drift_qa", "proof_scout", "market_desk", "shield")


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
        extra={"report_status": report.get("status"), "checked_at": report.get("checked_at"),
               "source_attribution": {"ops_evidence": "internal/ops/evidence.py"}},
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
        extra={"flags": flags, "source_attribution": {"ops_evidence": "internal/ops/evidence.py"}},
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
        extra={"observation": observation, "interpretation": interpretation,
               "source_attribution": {"ops_evidence": "internal/ops/evidence.py"}},
    )


def run_shield(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Security observer. Recommends only; never blocks. Does not invent abuse events."""
    del context
    from internal.write_auth import write_auth_enabled

    text = str(query or "").lower()
    observations = [
        f"write_api_token={'enabled' if write_auth_enabled() else 'unset'}",
    ]
    unknowns = [
        "no live request-log sample in this run; rate-limit/scrape/auth monitors need request context",
    ]
    in_scope = any(
        token in text
        for token in ("scrap", "rate limit", "auth", "abuse", "block user", "revoke")
    )
    return specialist_result(
        "shield",
        summary=(
            "shield in-scope: no abuse events claimed without request evidence"
            if in_scope
            else "shield observation-only: no request-log evidence in this run"
        ),
        status="ok",
        observations=observations,
        unknowns=unknowns,
        evidence=[],
        extra={
            "source_attribution": {"write_auth": "internal/write_auth.py"},
            "monitors": ("rate_limits", "scraping", "endpoint_misuse", "auth_abuse"),
        },
    )


_ADAPTERS: Dict[str, Specialist] = {
    "sentinel": run_sentinel,
    "drift_qa": run_drift_qa,
    "proof_scout": run_proof_scout,
    "market_desk": run_market_desk,
    "shield": run_shield,
}

# Snapshot-layer tags (Drift/QA) stay a separate enum from merge CONTRADICTION_TAGS.
# Only this mapping is clean enough to promote into the merge layer.
SNAPSHOT_TO_MERGE_TAG = {"live_label_vs_freshness": "stale_labeled_live"}
_STALE_LABELED_LIVE_FLAG = "stale_data_labeled_live"
_STALE_DATA_CHECK = "stale_data"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_items(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        rows: List[Any] = []
        for item in value:
            dumped = getattr(item, "to_dict", None)
            if callable(dumped):
                rows.append(dumped())
            elif isinstance(item, Mapping):
                rows.append(dict(item))
            else:
                rows.append(item)
        return rows
    dumped = getattr(value, "to_dict", None)
    if callable(dumped):
        return [dumped()]
    return [value]


def _snapshot_field_names(snapshot_type: Any) -> List[str]:
    try:
        if dataclasses.is_dataclass(snapshot_type):
            return [item.name for item in dataclasses.fields(snapshot_type)]
    except TypeError:
        pass
    try:
        return [
            param.name
            for param in inspect.signature(snapshot_type).parameters.values()
            if param.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and param.name != "self"
        ]
    except (TypeError, ValueError):
        return []


def _snapshot_from_context(module: Any, context: Mapping[str, Any]) -> Any:
    """Build DriftSnapshot from context keys that already exist. Do not invent fields."""
    existing = context.get("snapshot") if "snapshot" in context else context.get("drift_snapshot")
    snapshot_type = getattr(module, "DriftSnapshot", None)
    if existing is not None and (
        snapshot_type is None or isinstance(existing, snapshot_type)
    ):
        return existing
    if snapshot_type is None:
        return existing
    source: Mapping[str, Any]
    if isinstance(existing, Mapping):
        source = existing
    else:
        source = context
    kwargs = {name: source[name] for name in _snapshot_field_names(snapshot_type) if name in source}
    return snapshot_type(**kwargs)


def _contradiction_tags(report: Any) -> List[str]:
    tags: List[str] = []
    seen = set()
    for item in _get(report, "contradictions") or ():
        if isinstance(item, str):
            tag = item
        elif isinstance(item, Mapping):
            tag = item.get("tag")
        else:
            tag = getattr(item, "tag", None)
        if not tag:
            continue
        label = str(tag)
        if label in seen:
            continue
        seen.add(label)
        tags.append(label)
    return tags


def _flags_from_report(report: Any, tags: Sequence[str]) -> List[str]:
    flags: List[str] = []
    stale_data_flagged = False
    for check in _get(report, "checks") or ():
        name = _get(check, "name")
        flagged = bool(_get(check, "flagged"))
        if flagged and name:
            label = str(name)
            flags.append(label)
            if label == _STALE_DATA_CHECK:
                stale_data_flagged = True
    if "live_label_vs_freshness" in tags or stale_data_flagged:
        if _STALE_LABELED_LIVE_FLAG not in flags:
            flags.append(_STALE_LABELED_LIVE_FLAG)
    return flags


def specialist_result_from_observe(bot: str, report: Any) -> Dict[str, Any]:
    """Map an observe() DriftReport onto the specialist_result envelope.

    recommended_action is always None: observation is flag-only.
    Unmapped snapshot tags stay on snapshot_contradictions, not merge CONTRADICTION_TAGS.
    """
    tags = _contradiction_tags(report)
    snapshot_contradictions = [tag for tag in tags if tag not in SNAPSHOT_TO_MERGE_TAG]
    freshness = _get(report, "freshness")
    if isinstance(freshness, Mapping):
        freshness = dict(freshness)
    evidence = _as_items(_get(report, "evidence_bundles") or _get(report, "evidence"))
    return specialist_result(
        bot,
        summary=str(_get(report, "summary") or ""),
        status=str(_get(report, "status") or "ok"),
        observations=_as_items(_get(report, "observations")),
        evidence=evidence,
        unknowns=_as_items(_get(report, "unknowns")),
        recommended_action=None,
        freshness=freshness,
        confidence=_get(report, "confidence"),
        extra={
            "flags": _flags_from_report(report, tags),
            "snapshot_contradictions": snapshot_contradictions,
        },
    )


def _wrap_observe(name: str, module: Any, observe_fn: Callable[..., Any]) -> Specialist:
    def run(query: str, context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        del query
        snapshot = _snapshot_from_context(module, context or {})
        return specialist_result_from_observe(name, observe_fn(snapshot))

    return run


def resolve_specialist(name: str) -> Specialist:
    """Prefer ``run(query, context)``; else wrap ``observe(snapshot)``; else adapter."""
    try:
        module = importlib.import_module(f"internal.bots.{name}")
        runner = getattr(module, "run", None)
        if callable(runner):
            return runner
        observer = getattr(module, "observe", None)
        if callable(observer):
            return _wrap_observe(name, module, observer)
    except Exception:
        pass
    if name in _ADAPTERS:
        return _ADAPTERS[name]
    raise KeyError(f"unknown specialist bot: {name}")
