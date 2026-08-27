"""Proof Scout — read-only evidence gathering for one subnet.

Populates and classifies an ``EvidenceBundle`` from existing learning and ops
evidence. It does not invent a second lineage model: coarse populations come
from ``internal.learning.evidence.evidence_source``, and Policy §2 freshness
comes from ``internal.ops.bot_policy.classify_freshness``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from internal.learning.evidence import (
    SOURCE_POPULATIONS,
    evidence_population,
    evidence_source,
    stamp_evidence,
)
from internal.learning.predictions_store import load_predictions
from internal.ops.bot_policy import bot_contract, classify_freshness
from internal.ops.evidence import build_evidence_report

logger = logging.getLogger(__name__)

BOT_NAME = "proof_scout"

# Policy §2 source keys (``internal.ops.bot_policy.FRESHNESS_THRESHOLDS``).
# Populations are lineage; these keys select the matching freshness table.
_FRESHNESS_SOURCE_BY_POPULATION = {
    "council": "pick_audit",
    "shadow": "learning_outcomes",
    "pump": "pump_desk",
    "archive": "message_intel_archive",
}

_BULL = frozenset(
    {
        "long",
        "buy",
        "up",
        "bull",
        "bullish",
        "accumulate",
        "accumulating",
        "building",
        "just_started",
        "pump",
        "mild_pump",
    }
)
_BEAR = frozenset(
    {
        "short",
        "sell",
        "down",
        "bear",
        "bearish",
        "reduce",
        "dump",
        "mild_dump",
        "distribution",
        "decline",
    }
)
_FLAT = frozenset({"hold", "flat", "neutral", "sideways", "stable"})

_PAYLOAD_KEYS = (
    "id",
    "netuid",
    "name",
    "direction",
    "action",
    "correct",
    "outcome",
    "status",
    "pick_source",
    "predicted_pct",
    "created_at",
    "resolved_at",
    "captured_at",
    "pump_badge",
    "pump_claim",
    "verdict",
    "category",
    "published_netuid",
    "label",
    "mentions",
    "score",
)


@dataclass(frozen=True)
class EvidenceItem:
    """One attributed evidence row inside an ``EvidenceBundle``."""

    relation: str
    population: str
    evidence_population: str
    summary: str
    freshness: Dict[str, Any]
    attribution: Dict[str, Any]
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation": self.relation,
            "population": self.population,
            "evidence_population": self.evidence_population,
            "summary": self.summary,
            "freshness": dict(self.freshness),
            "attribution": dict(self.attribution),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """Per-subnet classified evidence. Distinct from the global ops report dict."""

    bot: str
    run_id: str
    status: str
    subject: str
    subnet_id: int
    claim: Optional[str]
    summary: str
    items: Tuple[EvidenceItem, ...]
    unknowns: Tuple[str, ...]
    populations: Dict[str, int]
    freshness: Dict[str, Any]
    confidence: Optional[float]
    approval: Dict[str, Any]
    approval_required: bool
    recommended_action: None
    audit: Dict[str, Any]

    @property
    def supporting(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == "supporting")

    @property
    def contradictory(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == "contradictory")

    @property
    def observations(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == "observation")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot": self.bot,
            "run_id": self.run_id,
            "status": self.status,
            "subject": self.subject,
            "subnet_id": self.subnet_id,
            "claim": self.claim,
            "summary": self.summary,
            "observations": [item.to_dict() for item in self.observations],
            "evidence": [item.to_dict() for item in self.items],
            "supporting": [item.to_dict() for item in self.supporting],
            "contradictory": [item.to_dict() for item in self.contradictory],
            "unknowns": list(self.unknowns),
            "populations": dict(self.populations),
            "freshness": dict(self.freshness),
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "approval": dict(self.approval),
            "approval_required": self.approval_required,
            "audit": dict(self.audit),
        }


def gather_evidence(
    subnet_id: Any,
    *,
    claim: Optional[str] = None,
    now: Optional[datetime] = None,
) -> EvidenceBundle:
    """Gather, classify, and package evidence for ``subnet_id``.

    Read-only: does not write predictions, ops artifacts, or approvals.
    """
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    checked_at = datetime.now(timezone.utc)
    reference = now or checked_at
    unknowns: List[str] = []
    sources_read: List[str] = []
    items: List[EvidenceItem] = []

    parsed = parse_subnet_id(subnet_id)
    if parsed is None:
        contract = bot_contract(source="learning_outcomes", degraded=True, confidence=None)
        return EvidenceBundle(
            bot=BOT_NAME,
            run_id=run_id,
            status="degraded",
            subject=str(subnet_id),
            subnet_id=-1,
            claim=_clean_claim(claim),
            summary=f"invalid subnet_id={subnet_id!r}",
            items=(),
            unknowns=("invalid subnet_id",),
            populations={name: 0 for name in SOURCE_POPULATIONS},
            freshness=contract["freshness"],
            confidence=None,
            approval=contract["approval"],
            approval_required=contract["approval_required"],
            recommended_action=None,
            audit={
                "sources_read": [],
                "duration_ms": _duration_ms(started),
            },
        )

    ops_report: Optional[Dict[str, Any]] = None
    ops_degraded = False
    try:
        ops_report = build_evidence_report()
        sources_read.append("ops.evidence")
    except Exception as exc:
        ops_degraded = True
        unknowns.append(f"ops.evidence unavailable: {exc}")
        logger.warning("proof_scout ops evidence failed for SN%s: %s", parsed, exc)

    try:
        ledger = load_predictions(persist=False)
        sources_read.append("learning.predictions")
        items.extend(
            _items_from_predictions(
                parsed,
                ledger,
                claim_hint=claim,
                now=reference,
            )
        )
    except Exception as exc:
        unknowns.append(f"learning.predictions unavailable: {exc}")
        logger.warning("proof_scout predictions failed for SN%s: %s", parsed, exc)

    if ops_report is not None:
        items.extend(
            _items_from_ops_report(
                parsed,
                ops_report,
                claim_hint=claim,
                now=reference,
                sources_read=sources_read,
            )
        )

    items.extend(
        _items_from_message_intel(
            parsed,
            claim_hint=claim,
            now=reference,
            sources_read=sources_read,
            unknowns=unknowns,
        )
    )

    resolved_claim = _clean_claim(claim) or _infer_claim(items)
    classified = tuple(
        _reclassify_item(item, resolved_claim) if resolved_claim else item for item in items
    )

    envelopes = [
        item.freshness
        for item in classified
        if item.freshness.get("authoritative") is True
    ]
    contract = bot_contract(
        sources=envelopes,
        confidence=_confidence(classified),
        state_changing=False,
    )
    freshness = contract["freshness"]
    worst = str(freshness.get("status") or "missing")
    if ops_degraded or worst == "degraded":
        status = "degraded"
    elif not classified:
        status = "ok"
        unknowns.append("no subnet-specific evidence found")
    elif worst == "stale":
        status = "degraded"
    else:
        status = "ok"

    counts = _population_counts(classified)
    summary = _summarize(parsed, resolved_claim, classified, worst)
    duration_ms = _duration_ms(started)
    logger.info(
        "proof_scout SN%s items=%s supporting=%s contradictory=%s freshness=%s",
        parsed,
        len(classified),
        sum(1 for item in classified if item.relation == "supporting"),
        sum(1 for item in classified if item.relation == "contradictory"),
        worst,
    )
    return EvidenceBundle(
        bot=BOT_NAME,
        run_id=run_id,
        status=status,
        subject=f"SN{parsed}",
        subnet_id=parsed,
        claim=resolved_claim,
        summary=summary,
        items=classified,
        unknowns=tuple(unknowns),
        populations=counts,
        freshness=freshness,
        confidence=contract["confidence"],
        approval=contract["approval"],
        approval_required=contract["approval_required"],
        recommended_action=None,
        audit={
            "sources_read": sources_read,
            "duration_ms": duration_ms,
            "ops_status": None if ops_report is None else ops_report.get("status"),
        },
    )


def parse_subnet_id(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip().upper()
    if text.startswith("SN"):
        text = text[2:].lstrip("-_ ")
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _duration_ms(started: float) -> int:
    return int(max(0.0, (time.monotonic() - started) * 1000))


def _clean_claim(claim: Optional[str]) -> Optional[str]:
    text = str(claim or "").strip()
    return text or None


def _token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _stance_of(*values: Any) -> Optional[str]:
    for value in values:
        token = _token(value)
        if not token:
            continue
        if token in _BULL:
            return "bull"
        if token in _BEAR:
            return "bear"
        if token in _FLAT:
            return "flat"
    return None


def _stance_from_row(row: Mapping[str, Any]) -> Optional[str]:
    stance = _stance_of(
        row.get("direction"),
        row.get("action"),
        row.get("pump_claim"),
        row.get("pump_badge"),
        row.get("predicted_direction"),
        row.get("label"),
        row.get("verdict"),
    )
    if stance:
        return stance
    try:
        predicted = float(row.get("predicted_pct"))
    except (TypeError, ValueError):
        return None
    if predicted > 0:
        return "bull"
    if predicted < 0:
        return "bear"
    return None


def _relation(
    item_stance: Optional[str],
    claim: Optional[str],
    *,
    correct: Any = None,
) -> str:
    claim_stance = _stance_of(claim)
    if not claim_stance or not item_stance:
        return "observation"
    agrees = item_stance == claim_stance
    if correct is False:
        agrees = not agrees
    return "supporting" if agrees else "contradictory"


def _population_of(row: Mapping[str, Any]) -> str:
    source = str(row.get("evidence_source") or evidence_source(dict(row)))
    return source if source in SOURCE_POPULATIONS else "unknown"


def _freshness_for(
    population: str,
    captured_at: Any,
    *,
    now: datetime,
    degraded: bool = False,
    archive: bool = False,
    policy_source: Optional[str] = None,
) -> Dict[str, Any]:
    archive = archive or population == "archive"
    unknown = population == "unknown"
    # Unknown lineage has no Policy §2 table. Do not borrow another source's
    # thresholds or treat its timestamp as a live-current claim.
    if unknown and policy_source is None:
        captured_at = None
    source = policy_source or _FRESHNESS_SOURCE_BY_POPULATION.get(population, "learning_outcomes")
    return classify_freshness(
        source,
        captured_at,
        now=now,
        degraded=degraded,
        mode="archive" if archive else None,
        authoritative=not (archive or unknown),
    )


def _slice_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in _PAYLOAD_KEYS if key in row}


def _attribution(
    *,
    module: str,
    origin: str,
    captured_at: Any,
    population: str,
    evidence_population: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "module": module,
        "origin": origin,
        "captured_at": str(captured_at) if captured_at else None,
        "population": population,
        "evidence_population": evidence_population,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _make_item(
    *,
    row: Mapping[str, Any],
    relation: str,
    population: str,
    evidence_population: str,
    summary: str,
    captured_at: Any,
    now: datetime,
    module: str,
    origin: str,
    policy_source: Optional[str] = None,
    degraded: bool = False,
    extra_attr: Optional[Mapping[str, Any]] = None,
) -> EvidenceItem:
    archive = population == "archive" or str(row.get("mode") or "").lower() == "archive"
    return EvidenceItem(
        relation=relation,
        population=population,
        evidence_population=evidence_population,
        summary=summary,
        freshness=_freshness_for(
            population,
            captured_at,
            now=now,
            degraded=degraded,
            archive=archive,
            policy_source=policy_source,
        ),
        attribution=_attribution(
            module=module,
            origin=origin,
            captured_at=captured_at,
            population=population,
            evidence_population=evidence_population,
            extra=extra_attr,
        ),
        payload=_slice_payload(row),
    )


def _row_netuid(row: Mapping[str, Any]) -> Optional[int]:
    try:
        return int(row.get("netuid"))
    except (TypeError, ValueError):
        return None


def _items_from_predictions(
    subnet_id: int,
    ledger: Mapping[str, Any],
    *,
    claim_hint: Optional[str],
    now: datetime,
) -> List[EvidenceItem]:
    items: List[EvidenceItem] = []
    for bucket in ("predictions", "resolved"):
        rows = ledger.get(bucket) or []
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict) or _row_netuid(raw) != subnet_id:
                continue
            row = dict(raw)
            stamp_evidence(row)
            population = _population_of(row)
            fine = str(row.get("evidence_population") or evidence_population(row))
            captured_at = row.get("resolved_at") or row.get("created_at")
            stance = _stance_from_row(row)
            relation = _relation(stance, claim_hint, correct=row.get("correct"))
            label = stance or str(row.get("status") or "record")
            summary = (
                f"{population} {bucket[:-1]} {label}"
                f"{' hit' if row.get('correct') is True else ''}"
                f"{' miss' if row.get('correct') is False else ''}"
            ).strip()
            items.append(
                _make_item(
                    row=row,
                    relation=relation,
                    population=population,
                    evidence_population=fine,
                    summary=summary,
                    captured_at=captured_at,
                    now=now,
                    module="internal.learning.evidence",
                    origin=f"predictions.{bucket}",
                    extra_attr={"prediction_id": row.get("id"), "bucket": bucket},
                )
            )
    return items


def _items_from_ops_report(
    subnet_id: int,
    report: Mapping[str, Any],
    *,
    claim_hint: Optional[str],
    now: datetime,
    sources_read: List[str],
) -> List[EvidenceItem]:
    items: List[EvidenceItem] = []
    pick = dict(report.get("pick_audit") or {}) if isinstance(report.get("pick_audit"), dict) else {}
    published = parse_subnet_id(pick.get("published_netuid"))
    pick_captured = _ops_source_captured_at(report, "pick_audit")
    pick_path = (report.get("paths") or {}).get("pick_audit")
    if pick_path:
        sources_read.append(str(pick_path))
        raw_pick = _read_json(str(pick_path))
        if raw_pick:
            pick.setdefault("action", raw_pick.get("action"))
            pick.setdefault("verdict", raw_pick.get("verdict"))
            pick_captured = (
                raw_pick.get("captured_at")
                or raw_pick.get("audited_at")
                or pick_captured
            )
            if published is None:
                published = parse_subnet_id(raw_pick.get("published_netuid"))
    if published == subnet_id:
        row = {
            "netuid": subnet_id,
            "published_netuid": published,
            "action": pick.get("action"),
            "verdict": pick.get("verdict"),
            "category": pick.get("category"),
            "captured_at": pick_captured,
            "pick_source": "daily_pick",
        }
        stamp_evidence(row)
        population = _population_of(row)
        correct = False if str(pick.get("verdict") or "").upper() == "MISS" else None
        relation = _relation(_stance_from_row(row), claim_hint, correct=correct)
        items.append(
            _make_item(
                row=row,
                relation=relation,
                population=population,
                evidence_population=str(row.get("evidence_population") or "council_published"),
                summary=f"pick_audit published SN{subnet_id} verdict={pick.get('verdict')}",
                captured_at=pick_captured,
                now=now,
                module="internal.ops.evidence",
                origin="pick_audit",
                policy_source="pick_audit",
                extra_attr={"verdict": pick.get("verdict")},
            )
        )
    elif published is not None:
        items.append(
            _make_item(
                row={"netuid": published, "published_netuid": published},
                relation="observation",
                population="council",
                evidence_population="council_published",
                summary=f"today's published pick is SN{published}, not SN{subnet_id}",
                captured_at=pick_captured,
                now=now,
                module="internal.ops.evidence",
                origin="pick_audit",
                policy_source="pick_audit",
            )
        )

    pump_path = (report.get("paths") or {}).get("pump_desk")
    if pump_path:
        sources_read.append(str(pump_path))
        items.extend(_items_from_pump_artifact(subnet_id, pump_path, claim_hint=claim_hint, now=now))
    return items


def _ops_source_captured_at(report: Mapping[str, Any], source_name: str) -> Any:
    for envelope in report.get("evidence_sources") or []:
        if isinstance(envelope, dict) and envelope.get("source") == source_name:
            return envelope.get("captured_at")
    return None


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _items_from_pump_artifact(
    subnet_id: int,
    path: str,
    *,
    claim_hint: Optional[str],
    now: datetime,
) -> List[EvidenceItem]:
    data = _read_json(path)
    if not data:
        return []
    captured_at = data.get("captured_at")
    items: List[EvidenceItem] = []
    for badge in data.get("actionable_badges") or []:
        if not isinstance(badge, dict) or _row_netuid(badge) != subnet_id:
            continue
        row = {
            "netuid": subnet_id,
            "name": badge.get("name"),
            "pump_badge": badge.get("badge"),
            "pick_source": "pump_lead",
            "captured_at": captured_at,
        }
        stamp_evidence(row)
        population = _population_of(row)
        relation = _relation(_stance_from_row(row), claim_hint)
        items.append(
            _make_item(
                row=row,
                relation=relation,
                population=population,
                evidence_population=str(row.get("evidence_population") or "pump_early"),
                summary=f"pump desk badge {badge.get('badge')}",
                captured_at=captured_at,
                now=now,
                module="internal.ops.evidence",
                origin="pump_desk.actionable_badges",
                policy_source="pump_desk",
            )
        )
    return items


def _items_from_message_intel(
    subnet_id: int,
    *,
    claim_hint: Optional[str],
    now: datetime,
    sources_read: List[str],
    unknowns: List[str],
) -> List[EvidenceItem]:
    try:
        from internal.message_intel.context import lookup_social_sentiment_for_netuid

        social = lookup_social_sentiment_for_netuid(subnet_id)
    except Exception as exc:
        unknowns.append(f"message_intel unavailable: {exc}")
        return []
    if not social:
        return []
    captured_at = social.get("captured_at") or social.get("last_message_at")
    if not captured_at:
        unknowns.append("message_intel has no capture timestamp")
        return []
    sources_read.append("message_intel.sentiment")
    row = {
        "netuid": subnet_id,
        "name": social.get("name"),
        "label": social.get("label"),
        "score": social.get("score"),
        "mentions": social.get("mentions"),
        "captured_at": captured_at,
    }
    relation = _relation(_stance_from_row(row), claim_hint)
    return [
        _make_item(
            row=row,
            relation=relation,
            population="unknown",
            evidence_population="unknown",
            summary=f"message_intel {social.get('label')} mentions={social.get('mentions')}",
            captured_at=row.get("captured_at"),
            now=now,
            module="internal.message_intel.context",
            origin="netuid_sentiment_rollup",
            policy_source="message_intel_live",
            extra_attr={"source": "message_intel"},
        )
    ]


def _infer_claim(items: Sequence[EvidenceItem]) -> Optional[str]:
    for item in items:
        if item.population != "council":
            continue
        stance = _stance_from_row(item.payload)
        if stance == "bull":
            return "LONG"
        if stance == "bear":
            return "SHORT"
        if stance == "flat":
            return "HOLD"
    return None


def _reclassify_item(item: EvidenceItem, claim: Optional[str]) -> EvidenceItem:
    if not claim or item.relation != "observation":
        return item
    relation = _relation(_stance_from_row(item.payload), claim, correct=item.payload.get("correct"))
    if relation == item.relation:
        return item
    return EvidenceItem(
        relation=relation,
        population=item.population,
        evidence_population=item.evidence_population,
        summary=item.summary,
        freshness=item.freshness,
        attribution=item.attribution,
        payload=item.payload,
    )


def _population_counts(items: Iterable[EvidenceItem]) -> Dict[str, int]:
    counts = {name: 0 for name in SOURCE_POPULATIONS}
    for item in items:
        key = item.population if item.population in counts else "unknown"
        counts[key] += 1
    return counts


def _confidence(items: Sequence[EvidenceItem]) -> Optional[float]:
    decided = [
        item
        for item in items
        if item.relation in {"supporting", "contradictory"}
        and item.freshness.get("authoritative") is True
        and item.population not in {"archive", "unknown"}
    ]
    if not decided:
        return None
    supporting = sum(1 for item in decided if item.relation == "supporting")
    return round(supporting / len(decided), 3)


def _summarize(
    subnet_id: int,
    claim: Optional[str],
    items: Sequence[EvidenceItem],
    freshness_status: str,
) -> str:
    supporting = sum(1 for item in items if item.relation == "supporting")
    contradictory = sum(1 for item in items if item.relation == "contradictory")
    observations = sum(1 for item in items if item.relation == "observation")
    claim_bit = f" claim={claim}" if claim else ""
    return (
        f"SN{subnet_id}{claim_bit}: {supporting} supporting, {contradictory} contradictory, "
        f"{observations} observations; freshness={freshness_status}"
    )
