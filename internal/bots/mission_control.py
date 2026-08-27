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
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from internal.approval.service import (
    ApprovalDenied,
    ApprovalRecord,
    enforce_approval,
    request_approval,
)
from internal.bots.specialists import resolve_specialist, specialist_result
from internal.ops.bot_policy import (
    aggregate_freshness,
    approval_for,
    bot_contract,
    classify_freshness,
)
from internal.ops.notify import log_event

logger = logging.getLogger(__name__)

INTENTS = ("monitor", "analyze", "explain", "recommend")
RISK_LEVELS = ("low", "medium", "high", "critical")
SPECIALIST_TIMEOUT_SECONDS = 8
# Overlay on FRESHNESS_THRESHOLDS: any insight older than 4h is suspect.
INSIGHT_SUSPECT_SECONDS = 4 * 3600

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
    "recommend": ("market_desk", "proof_scout", "sentinel", "drift_qa", "shield"),
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
    if any(token in text for token in ("scrap", "rate limit", "auth abuse", "block user")):
        if "shield" not in names:
            names.append("shield")
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
    """Surface conflicting specialist conclusions instead of averaging them.

    Tags are the Policy §4 enum in ``internal.ops.bot_policy.CONTRADICTION_TAGS``.
    """
    contradictions: List[Dict[str, Any]] = []
    stances: Dict[str, List[str]] = {}
    actions: Dict[str, List[str]] = {}
    populations: Dict[str, List[str]] = {}
    freshness_by_source: Dict[str, Dict[str, List[str]]] = {}
    supporting_bots: List[str] = []
    contradictory_bots: List[str] = []
    for result in results:
        bot = str(result.get("bot") or "unknown")
        stance = _STATUS_STANCE.get(str(result.get("status") or "").lower())
        if stance:
            stances.setdefault(stance, []).append(bot)
        action = str(result.get("recommended_action") or "").strip().lower()
        if action:
            mapped = _ACTION_STANCE.get(action, action)
            actions.setdefault(mapped, []).append(bot)
        if result.get("supporting"):
            supporting_bots.append(bot)
        if result.get("contradictory"):
            contradictory_bots.append(bot)
        for item in result.get("evidence") or []:
            if isinstance(item, dict) and item.get("population"):
                populations.setdefault(str(item["population"]), []).append(bot)
        for src in _sources_of(result):
            source_name = str(src.get("source") or "unknown")
            status = str(src.get("status") or "missing")
            freshness_by_source.setdefault(source_name, {}).setdefault(status, []).append(bot)
        flags = result.get("flags") or []
        if "stale_data_labeled_live" in flags:
            contradictions.append(
                {
                    "tag": "stale_labeled_live",
                    "detail": f"{bot} flagged stale data labeled live",
                    "bots": [bot],
                }
            )
    if len(stances) > 1:
        contradictions.append(
            {
                "tag": "status_disagreement",
                "detail": "specialists disagree on health stance",
                "by_stance": stances,
            }
        )
    if len(actions) > 1:
        contradictions.append(
            {
                "tag": "recommended_action_conflict",
                "detail": "specialists recommend incompatible actions",
                "by_action": actions,
            }
        )
    if supporting_bots and contradictory_bots:
        contradictions.append(
            {
                "tag": "supporting_vs_contradictory",
                "detail": "evidence bundles both support and contradict the claim",
                "supporting_bots": supporting_bots,
                "contradictory_bots": contradictory_bots,
            }
        )
    live_pops = {k: v for k, v in populations.items() if k != "unknown"}
    if len(live_pops) > 1:
        contradictions.append(
            {
                "tag": "population_mix",
                "detail": "evidence populations mixed without a shared lineage",
                "by_population": live_pops,
            }
        )
    for source_name, by_status in freshness_by_source.items():
        if len(by_status) > 1:
            contradictions.append(
                {
                    "tag": "freshness_disagreement",
                    "detail": f"{source_name} freshness disagrees across specialists",
                    "source": source_name,
                    "by_status": by_status,
                }
            )
    return contradictions


def _age_seconds(envelope: Mapping[str, Any]) -> Optional[float]:
    raw = envelope.get("age_seconds")
    try:
        if raw is not None:
            return float(raw)
    except (TypeError, ValueError):
        pass
    captured = envelope.get("captured_at") or envelope.get("observed_at")
    if not captured:
        return None
    try:
        parsed = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _canonicalize_freshness(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Per-source thresholds plus the 4h suspect overlay. Never claim fresh if suspect."""
    result = dict(envelope)
    status = str(result.get("status") or "missing").lower()
    result["status"] = status
    age_value = _age_seconds(result)
    if age_value is not None:
        result["age_seconds"] = round(age_value, 1)
    suspect = age_value is not None and age_value > INSIGHT_SUSPECT_SECONDS
    result["suspect_over_4h"] = bool(suspect)
    if suspect and status == "fresh":
        result["status"] = "aging"
        status = "aging"
    result["claim_fresh"] = status == "fresh" and not suspect
    result["enforced"] = True
    return result


def enforce_freshness(sources: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Policy §5: a stale/missing/degraded source cannot yield a fresh conclusion."""
    canonical = [_canonicalize_freshness(item) for item in sources] if sources else []
    envelope = aggregate_freshness(canonical) if canonical else classify_freshness("learning_health")
    return _canonicalize_freshness(envelope)


def _normalize_specialist_freshness(result: Mapping[str, Any]) -> Dict[str, Any]:
    payload = dict(result)
    freshness = payload.get("freshness")
    if isinstance(freshness, dict):
        payload["freshness"] = _canonicalize_freshness(freshness)
        nested = payload["freshness"].get("sources")
        if isinstance(nested, list):
            payload["freshness"]["sources"] = [
                _canonicalize_freshness(item) if isinstance(item, dict) else item
                for item in nested
            ]
    return payload


def _incomplete_specialists(results: Mapping[str, Mapping[str, Any]]) -> List[str]:
    incomplete: List[str] = []
    for name, result in results.items():
        status = str(result.get("status") or "")
        if status in {"degraded", "blocked"} or result.get("unknowns") and status != "ok":
            incomplete.append(name)
        if "unavailable" in str(result.get("summary") or "").lower() or "timed out" in str(result.get("summary") or "").lower():
            if name not in incomplete:
                incomplete.append(name)
    return incomplete


def _is_uncertain(
    results: Mapping[str, Mapping[str, Any]],
    freshness: Mapping[str, Any],
    contradictions: Sequence[Mapping[str, Any]],
    incomplete: Sequence[str],
) -> bool:
    if contradictions or incomplete:
        return True
    if freshness.get("suspect_over_4h"):
        return True
    if str(freshness.get("status") or "") in {"stale", "missing", "degraded"}:
        return True
    for result in results.values():
        conf = result.get("confidence")
        try:
            if conf is not None and float(conf) < 0.4:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _traced_claims(results: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Only claims that trace to a source envelope. Never fabricate."""
    claims: List[Dict[str, Any]] = []
    for name, result in results.items():
        if str(result.get("status") or "") in {"degraded", "blocked"}:
            continue
        text = str(result.get("summary") or "").strip()
        sources = _sources_of(result)
        evidence = result.get("evidence") or []
        if not text or not sources or not evidence:
            continue
        claims.append(
            {
                "bot": name,
                "text": text,
                "source_attribution": result.get("source_attribution")
                or [src.get("source") for src in sources],
                "freshness": result.get("freshness"),
                "evidence": result.get("evidence") or [],
            }
        )
    return claims


def _run_one(
    name: str,
    query: str,
    context: Mapping[str, Any],
    runners: Mapping[str, Callable[..., Dict[str, Any]]],
) -> Dict[str, Any]:
    runner = runners.get(name)
    if runner is None:
        return _normalize_specialist_freshness(
            specialist_result(
                name,
                summary=f"{name} unavailable: specialist not registered",
                status="degraded",
                unknowns=["specialist_unavailable"],
                sources=[classify_freshness("learning_health", degraded=True)],
            )
        )
    try:
        result = runner(query, context)
        if not isinstance(result, dict):
            raise TypeError(f"{name} returned {type(result)!r}")
        result.setdefault("bot", name)
        return _normalize_specialist_freshness(result)
    except Exception as exc:
        logger.warning("specialist %s failed: %s", name, exc)
        return _normalize_specialist_freshness(
            specialist_result(
                name,
                summary=f"{name} failed: {exc}",
                status="degraded",
                unknowns=[str(exc)],
                sources=[classify_freshness("learning_health", degraded=True)],
            )
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
    pool = ThreadPoolExecutor(max_workers=max(1, len(names)))
    futures = {
        pool.submit(_run_one, name, query, context, runners): name for name in names
    }
    try:
        done, not_done = wait(list(futures), timeout=SPECIALIST_TIMEOUT_SECONDS)
        for future in done:
            name = futures[future]
            try:
                ordered[name] = future.result()
            except Exception as exc:
                ordered[name] = _normalize_specialist_freshness(
                    specialist_result(
                        name,
                        summary=f"{name} failed: {exc}",
                        status="degraded",
                        unknowns=[str(exc)],
                        sources=[classify_freshness("learning_health", degraded=True)],
                    )
                )
        for future in not_done:
            name = futures[future]
            ordered[name] = _normalize_specialist_freshness(
                specialist_result(
                    name,
                    summary=f"{name} timed out after {SPECIALIST_TIMEOUT_SECONDS}s",
                    status="degraded",
                    unknowns=["timeout"],
                    sources=[classify_freshness("learning_health", degraded=True)],
                )
            )
    finally:
        # ponytail: in-flight specialists keep running; we do not block /health
        # on them. Upgrade path: per-bot timeouts inside the adapters.
        pool.shutdown(wait=False, cancel_futures=True)
    return {name: ordered[name] for name in names if name in ordered}


class MissionControl:
    def __init__(
        self,
        specialists: Optional[Mapping[str, Callable[..., Dict[str, Any]]]] = None,
    ) -> None:
        self._specialists = dict(specialists) if specialists else None

    def _runners(self, names: Sequence[str]) -> Dict[str, Callable[..., Dict[str, Any]]]:
        if self._specialists is not None:
            return dict(self._specialists)
        resolved: Dict[str, Callable[..., Dict[str, Any]]] = {}
        for name in names:
            try:
                resolved[name] = resolve_specialist(name)
            except KeyError:
                continue
        return resolved

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
        log_event(
            "mission_control.route",
            run_id=run_id,
            intent=resolved_intent,
            risk_level=risk_level,
            routed_to=list(names),
            query=query,
        )
        context = {"subject": subject, "intent": resolved_intent, "run_id": run_id}
        results = _run_parallel(names, query, context, self._runners(names))

        sources: List[Dict[str, Any]] = []
        for result in results.values():
            sources.extend(_sources_of(result))
        freshness = enforce_freshness(sources)
        contradictions = detect_contradictions(list(results.values()))
        incomplete = _incomplete_specialists(results)
        uncertain = _is_uncertain(results, freshness, contradictions, incomplete)

        if uncertain and risk_level == "low":
            risk_level = "medium"

        state_changing = _is_state_changing(query, resolved_intent)
        if risk_level == "critical":
            state_changing = True
        # Policy §3.1: critical + high-risk + uncertain all go through the approval gate
        # BEFORE sharing. Sharing a held finding is the gated action.
        approval_required = risk_level in {"critical", "high"} or uncertain or state_changing

        status = "ok"
        if incomplete:
            status = "incomplete"
        elif freshness.get("status") in {"stale", "missing", "degraded"} or contradictions:
            status = "degraded"
        elif any(item.get("status") in {"degraded", "blocked"} for item in results.values()):
            status = "degraded"

        claims = _traced_claims(results)
        shareable = not approval_required and status == "ok"
        if approval_required:
            summary = "held pending human approval before sharing (Policy §3.1)"
        elif status == "incomplete":
            summary = "incomplete: specialists unavailable or degraded; synthesis withheld"
        elif contradictions:
            summary = "specialist contradiction: results surfaced, not averaged"
        elif status == "degraded" and freshness.get("status") in {"stale", "missing", "degraded"}:
            summary = f"degraded: evidence freshness is {freshness.get('status')}"
        elif claims:
            summary = str(claims[0]["text"])
        else:
            summary = "no sourced specialist claim"

        category = _action_category(query, resolved_intent)
        approval_payload = approval_for(category, state_changing=approval_required)
        if approval_required:
            record = request_approval(
                action_type=resolved_intent,
                risk_level=risk_level,
                evidence_refs=[src.get("source") or "unknown" for src in sources],
                requested_by=requested_by,
                action_category=category,
                proposal={
                    "query": query,
                    "subject": subject,
                    "shareable": False,
                    "specialists": results,
                    "claims": claims,
                    "recommended_actions": [
                        item.get("recommended_action")
                        for item in results.values()
                        if item.get("recommended_action")
                    ],
                },
                freshness=freshness,
                run_id=run_id,
                state_changing=True,
            )
            approval_payload = record.to_contract()

        confidences = []
        for item in results.values():
            try:
                if item.get("confidence") is not None:
                    confidences.append(float(item["confidence"]))
            except (TypeError, ValueError):
                pass
        merged_confidence = min(confidences) if confidences else None
        contract = bot_contract(
            freshness=freshness,
            confidence=merged_confidence,
            action_category=category,
            state_changing=approval_required,
        )
        contract["freshness"] = freshness
        contract["approval"] = approval_payload
        contract["approval_required"] = bool(approval_required)
        if isinstance(contract.get("approval"), dict):
            contract["approval"]["required"] = bool(approval_required)

        public_specialists = results
        approval_packet = None
        if not shareable:
            public_specialists = {
                name: {
                    "bot": item.get("bot") or name,
                    "status": item.get("status"),
                    "freshness": item.get("freshness"),
                }
                for name, item in results.items()
            }
            approval_packet = {"specialists": results, "claims": claims, "contradictions": contradictions}

        merged = {
            "status": status,
            "summary": summary,
            "subject": subject,
            "run_id": run_id,
            "routed_to": names,
            "specialists": public_specialists,
            "contradictions": contradictions,
            "incomplete_specialists": incomplete,
            "uncertain": uncertain,
            "shareable": shareable,
            "claims": claims if shareable else [],
            "approval_packet": approval_packet,
            "freshness": freshness,
            "state_changing": state_changing,
        }
        merged.update(contract)
        log_event(
            "mission_control.decision",
            run_id=run_id,
            intent=resolved_intent,
            risk_level=risk_level,
            approval_required=approval_required,
            status=status,
            shareable=shareable,
            incomplete_specialists=incomplete,
            contradiction_tags=[c.get("tag") for c in contradictions],
            approval_id=approval_payload.get("approval_id") if isinstance(approval_payload, dict) else None,
        )
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
