"""Mission Control — supervisory coordinator for SimiVision specialist bots.

Classifies intent, assesses Policy §3.1 risk, fans out specialists in
parallel, merges evidence with contradiction detection, enforces Policy §5
freshness (degraded when stale), and routes proposed actions through
``internal.approval.service``. Does not mutate Soul-Map, learning, registry,
or deployment state.
"""

from __future__ import annotations

import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from internal.approval.service import (
    ApprovalDenied,
    ApprovalRecord,
    enforce_approval,
    request_approval,
)
from internal.bots.specialists import resolve_specialist, specialist_result
from internal.ops.bot_policy import aggregate_freshness, classify_freshness

logger = logging.getLogger(__name__)

INTENTS = ("monitor", "analyze", "explain", "recommend")
RISK_LEVELS = ("low", "medium", "high", "critical")
SPECIALIST_TIMEOUT_SECONDS = 8

# Policy §3.1 — critical actions always require a human approval record.
_CRITICAL_PATTERNS = (
    "restart",
    "redeploy",
    "delete data",
    "drop volume",
    "block user",
    "revoke access",
    "execute trade",
    "move funds",
    "edit registry",
    "write soul_map",
    "change learned weights",
    "kill worker",
    "force deploy",
)
_STATE_CHANGING_PATTERNS = (
    "restart",
    "redeploy",
    "publish",
    "scale",
    "rate limit",
    "change weight",
    "grading correction",
    "block",
    "remediate",
    "draft a release",
)
_RECOMMEND_HINTS = (
    "recommend",
    "should we",
    "restart",
    "redeploy",
    "publish",
    "draft a release",
    "change weight",
    "remediate",
    "fix the",
    "scale ",
)
_MONITOR_HINTS = (
    "health",
    "uptime",
    "stale",
    "latency",
    "worker",
    "dashboard feels",
    "readiness",
    "heartbeat",
    "monitor",
    "warming",
    "degraded",
)
_ANALYZE_HINTS = (
    "underperforming",
    "compare",
    "trend",
    "movement",
    "trustworthy",
    "analyze",
    "signal",
    "why is",
)
_EXPLAIN_HINTS = (
    "what is",
    "explain",
    "how does",
    "terminology",
    "why did",
    "meaning of",
)
_SN_RE = re.compile(r"\b(?:sn|subnet|netuid)\s*#?\s*(\d{1,3})\b", re.I)

_INTENT_SPECIALISTS: Dict[str, tuple[str, ...]] = {
    "monitor": ("sentinel", "drift_qa"),
    "analyze": ("market_desk", "proof_scout"),
    "explain": ("market_desk", "proof_scout"),
    "recommend": ("market_desk", "proof_scout", "sentinel"),
}

_STATUS_STANCE = {
    "ok": "healthy",
    "warn": "watch",
    "alert": "unhealthy",
    "degraded": "unhealthy",
    "blocked": "blocked",
}
_ACTION_STANCE = {
    "restart": "mutate_infra",
    "redeploy": "mutate_infra",
    "hold": "hold",
    "buy": "long",
    "long": "long",
    "sell": "short",
    "short": "short",
    "publish": "publish",
}


@dataclass(frozen=True)
class MissionControlResponse:
    intent: str
    risk_level: str
    merged_results: Dict[str, Any]
    approval_required: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_intent(query: str) -> str:
    text = str(query or "").strip().lower()
    if any(hint in text for hint in _RECOMMEND_HINTS):
        return "recommend"
    if any(hint in text for hint in _MONITOR_HINTS):
        return "monitor"
    if any(hint in text for hint in _ANALYZE_HINTS):
        return "analyze"
    if any(hint in text for hint in _EXPLAIN_HINTS):
        return "explain"
    return "explain"


def _is_critical_query(text: str) -> bool:
    return any(token in text for token in _CRITICAL_PATTERNS)


def _is_state_changing(text: str, intent: str) -> bool:
    if _is_critical_query(text):
        return True
    if intent == "recommend" and any(token in text for token in _STATE_CHANGING_PATTERNS):
        return True
    return False


def assess_risk(query: str, intent: str = "explain") -> str:
    """Policy §3.1 risk taxonomy. Critical always requires human approval."""
    text = str(query or "").strip().lower()
    if _is_critical_query(text):
        return "critical"
    if intent == "recommend" or _is_state_changing(text, intent):
        return "high"
    if intent == "analyze":
        return "medium"
    return "low"


def extract_subject(query: str) -> Optional[str]:
    match = _SN_RE.search(str(query or ""))
    return f"SN{match.group(1)}" if match else None


def select_specialists(intent: str, query: str = "") -> List[str]:
    names = list(_INTENT_SPECIALISTS.get(intent, _INTENT_SPECIALISTS["explain"]))
    text = str(query or "").lower()
    if intent in {"analyze", "explain"} and any(
        token in text for token in ("stale", "fresh", "live", "archive", "trustworthy")
    ):
        if "sentinel" not in names:
            names.append("sentinel")
    return names


def _action_category(query: str, intent: str) -> Optional[str]:
    text = str(query or "").lower()
    if any(token in text for token in ("restart", "redeploy", "scale", "worker", "deploy")):
        return "infrastructure"
    if any(token in text for token in ("block", "rate limit", "revoke", "scrap")):
        return "security"
    if any(token in text for token in ("weight", "grading", "learning")):
        return "learning"
    if any(token in text for token in ("publish", "release note", "documentation")):
        return "content"
    if intent == "recommend":
        return "unknown"
    return None


def _sources_of(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    freshness = result.get("freshness")
    if isinstance(freshness, dict) and isinstance(freshness.get("sources"), list) and freshness["sources"]:
        return [dict(item) for item in freshness["sources"] if isinstance(item, dict)]
    if isinstance(freshness, dict) and freshness.get("status"):
        return [dict(freshness)]
    return []


def detect_contradictions(results: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Surface conflicting specialist conclusions instead of averaging them."""
    contradictions: List[Dict[str, Any]] = []
    stances: Dict[str, List[str]] = {}
    actions: Dict[str, List[str]] = {}
    for result in results:
        bot = str(result.get("bot") or "unknown")
        stance = _STATUS_STANCE.get(str(result.get("status") or "").lower())
        if stance:
            stances.setdefault(stance, []).append(bot)
        action = str(result.get("recommended_action") or "").strip().lower()
        if action:
            mapped = _ACTION_STANCE.get(action, action)
            actions.setdefault(mapped, []).append(bot)
    if len(stances) > 1:
        contradictions.append(
            {
                "type": "status",
                "detail": "specialists disagree on health stance",
                "by_stance": stances,
            }
        )
    if len(actions) > 1:
        contradictions.append(
            {
                "type": "recommended_action",
                "detail": "specialists recommend incompatible actions",
                "by_action": actions,
            }
        )
    return contradictions


def enforce_freshness(sources: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Policy §5: a stale/missing/degraded source cannot yield a fresh conclusion."""
    envelope = aggregate_freshness(sources) if sources else classify_freshness("learning_health")
    status = str(envelope.get("status") or "missing")
    degraded = status in {"stale", "missing", "degraded"}
    envelope["enforced"] = True
    envelope["claim_fresh"] = status == "fresh" and not degraded
    return envelope


def _run_one(
    name: str,
    query: str,
    context: Mapping[str, Any],
    runners: Mapping[str, Callable[..., Dict[str, Any]]],
) -> Dict[str, Any]:
    runner = runners[name]
    try:
        result = runner(query, context)
        if not isinstance(result, dict):
            raise TypeError(f"{name} returned {type(result)!r}")
        result.setdefault("bot", name)
        return result
    except Exception as exc:
        logger.warning("specialist %s failed: %s", name, exc)
        return specialist_result(
            name,
            summary=f"{name} failed: {exc}",
            status="degraded",
            unknowns=[str(exc)],
            sources=[classify_freshness("learning_health", degraded=True)],
        )


def _run_parallel(
    names: Sequence[str],
    query: str,
    context: Mapping[str, Any],
    runners: Mapping[str, Callable[..., Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    if not names:
        return {}
    ordered: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        futures = {
            pool.submit(_run_one, name, query, context, runners): name for name in names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                ordered[name] = future.result(timeout=SPECIALIST_TIMEOUT_SECONDS)
            except Exception as exc:
                ordered[name] = specialist_result(
                    name,
                    summary=f"{name} timed out or failed: {exc}",
                    status="degraded",
                    unknowns=[str(exc)],
                    sources=[classify_freshness("learning_health", degraded=True)],
                )
    return {name: ordered[name] for name in names if name in ordered}


class MissionControl:
    def __init__(
        self,
        specialists: Optional[Mapping[str, Callable[..., Dict[str, Any]]]] = None,
    ) -> None:
        self._specialists = dict(specialists) if specialists else None

    def _runners(self, names: Sequence[str]) -> Dict[str, Callable[..., Dict[str, Any]]]:
        if self._specialists is not None:
            return {name: self._specialists[name] for name in names}
        return {name: resolve_specialist(name) for name in names}

    def handle(
        self,
        query: str,
        *,
        requested_by: str = "mission_control",
        intent: Optional[str] = None,
        specialists: Optional[Sequence[str]] = None,
    ) -> MissionControlResponse:
        run_id = str(uuid.uuid4())
        resolved_intent = intent if intent in INTENTS else classify_intent(query)
        risk_level = assess_risk(query, resolved_intent)
        names = list(specialists) if specialists is not None else select_specialists(resolved_intent, query)
        subject = extract_subject(query)
        context = {"subject": subject, "intent": resolved_intent, "run_id": run_id}
        results = _run_parallel(names, query, context, self._runners(names))

        sources: List[Dict[str, Any]] = []
        for result in results.values():
            sources.extend(_sources_of(result))
        freshness = enforce_freshness(sources)
        contradictions = detect_contradictions(list(results.values()))

        state_changing = _is_state_changing(query, resolved_intent)
        if risk_level == "critical":
            state_changing = True
        approval_required = risk_level == "critical" or state_changing

        status = "ok"
        if freshness.get("status") in {"stale", "missing", "degraded"}:
            status = "degraded"
        if contradictions:
            status = "degraded"
        if any(item.get("status") in {"degraded", "blocked"} for item in results.values()):
            status = "degraded"

        summaries = [str(item.get("summary") or "") for item in results.values() if item.get("summary")]
        if contradictions:
            summary = "specialist contradiction: results surfaced, not averaged"
        elif status == "degraded" and freshness.get("status") in {"stale", "missing", "degraded"}:
            summary = f"degraded: evidence freshness is {freshness.get('status')}"
        elif summaries:
            summary = summaries[0]
        else:
            summary = "no specialist summary"

        approval_payload: Optional[Dict[str, Any]] = None
        if approval_required:
            record = request_approval(
                action_type=resolved_intent,
                risk_level=risk_level,
                evidence_refs=[src.get("source") or "unknown" for src in sources],
                requested_by=requested_by,
                action_category=_action_category(query, resolved_intent),
                proposal={"query": query, "subject": subject, "recommended_actions": [
                    item.get("recommended_action")
                    for item in results.values()
                    if item.get("recommended_action")
                ]},
                freshness=freshness,
                run_id=run_id,
                state_changing=True,
            )
            approval_payload = record.to_dict()

        merged = {
            "status": status,
            "summary": summary,
            "subject": subject,
            "run_id": run_id,
            "routed_to": names,
            "specialists": results,
            "contradictions": contradictions,
            "freshness": freshness,
            "approval": approval_payload,
            "state_changing": state_changing,
        }
        return MissionControlResponse(
            intent=resolved_intent,
            risk_level=risk_level,
            merged_results=merged,
            approval_required=approval_required,
        )


def handle(query: str, **kwargs: Any) -> MissionControlResponse:
    return MissionControl().handle(query, **kwargs)


def gate_execution(approval_id: str) -> ApprovalRecord:
    """The only mutation gate Mission Control exposes — still does not mutate."""
    return enforce_approval(approval_id)


def cannot_execute_without_approval(approval_id: Optional[str]) -> None:
    if not approval_id:
        raise ApprovalDenied("no approval = no mutation")
    enforce_approval(approval_id)
