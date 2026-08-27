"""Observation-only Drift / QA bot.

Flags data and UI drift. Never blocks requests, never retries hydrations,
never writes production state, and never auto-heals. Callers pass a snapshot;
this module inspects it once and reports.

Policy mapping (governance markdown is not in-repo; these are the in-repo
surfaces — not a parallel scheme):
- §2.3 freshness disclosure on every claim via ``classify_freshness``
  envelopes (``internal.ops.bot_policy``), same string form as the approved
  governance draft: ``Evidence freshness: {source} is {status} ({age}).``
- §3.1 risk classes exactly ``low|medium|high|critical`` (Shield
  ``RISK_CLASSES`` / Mission Control ``RISK_LEVELS``; no ``info``; unknown
  labels fail closed to ``critical``).
- §4 evidence hygiene: source attribution, supporting vs contradictory vs
  observation (Proof Scout ``relation``), ``WARNING: source unavailable``
  instead of silent fallback, contradiction tags that name *what disagreed*.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from internal.ops.bot_policy import aggregate_freshness, bot_contract, classify_freshness

BOT_NAME = "drift_qa"
OBSERVATION_ONLY = True
MUTATIONS_ALLOWED = False
RETRIES_ALLOWED = False
STUCK_PANEL_TIMEOUT_SECONDS = 10.0

# Policy §3.1 — exact set. Every finding.severity is one of these four.
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"
RISK_CLASSES: Tuple[str, ...] = (
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_HIGH,
    SEVERITY_CRITICAL,
)
_RISK_ORDER = {SEVERITY_LOW: 0, SEVERITY_MEDIUM: 1, SEVERITY_HIGH: 2, SEVERITY_CRITICAL: 3}

# Policy §4 evidence hygiene: supporting / contradictory / unavailable.
# Unavailable is required so a missing source is disclosed instead of silently
# filled from cache (no-silent-fallback). Bundle items use the Proof Scout
# relation set (supporting | contradictory | observation).
EVIDENCE_SUPPORTING = "supporting"
EVIDENCE_CONTRADICTORY = "contradictory"
EVIDENCE_UNAVAILABLE = "unavailable"
EVIDENCE_OBSERVATION = "observation"
EVIDENCE_RELATIONS: Tuple[str, ...] = (
    EVIDENCE_SUPPORTING,
    EVIDENCE_CONTRADICTORY,
    EVIDENCE_OBSERVATION,
)

CHECK_MISSING_FIELDS = "missing_fields"
CHECK_SHAPE_CHANGES = "shape_changes"
CHECK_HYDRATION_FAILS = "hydration_fails"
CHECK_STUCK_PANELS = "stuck_panels"
CHECK_STALE_DATA = "stale_data"
CHECK_DISAGREEMENT = "disagreement"
CHECK_READINESS_DROPS = "readiness_drops"
CHECK_DEGRADED_HTTP_200S = "degraded_http_200s"

CHECKS: Tuple[str, ...] = (
    CHECK_MISSING_FIELDS,
    CHECK_SHAPE_CHANGES,
    CHECK_HYDRATION_FAILS,
    CHECK_STUCK_PANELS,
    CHECK_STALE_DATA,
    CHECK_DISAGREEMENT,
    CHECK_READINESS_DROPS,
    CHECK_DEGRADED_HTTP_200S,
)

# Policy §4 contradiction tags — names of *what disagreed*, not a root cause.
# These are intra-snapshot drift tags (Mission Control's specialist-merge
# types status|recommended_action are a different layer).
TAG_SOURCES_DISAGREE = "sources_disagree"
TAG_LIVE_VS_FRESHNESS = "live_label_vs_freshness"
TAG_SHAPE_VS_SCHEMA = "shape_vs_schema"
TAG_SSR_VS_CLIENT = "ssr_vs_client"
TAG_HTTP_OK_VS_DEGRADED = "http_ok_vs_degraded_body"
TAG_READINESS_VS_PRIOR = "readiness_vs_prior"
CONTRADICTION_TAGS: Tuple[str, ...] = (
    TAG_SOURCES_DISAGREE,
    TAG_LIVE_VS_FRESHNESS,
    TAG_SHAPE_VS_SCHEMA,
    TAG_SSR_VS_CLIENT,
    TAG_HTTP_OK_VS_DEGRADED,
    TAG_READINESS_VS_PRIOR,
)

# §3.1 mapping for *flagged* drift (observation-only; never triggers approval).
# Unobserved/unavailable checks stay low. Unknown labels fail closed to critical.
_FLAGGED_SEVERITY = {
    CHECK_MISSING_FIELDS: SEVERITY_HIGH,
    CHECK_SHAPE_CHANGES: SEVERITY_HIGH,
    CHECK_HYDRATION_FAILS: SEVERITY_HIGH,
    CHECK_STUCK_PANELS: SEVERITY_HIGH,
    CHECK_STALE_DATA: SEVERITY_CRITICAL,
    CHECK_DISAGREEMENT: SEVERITY_HIGH,
    CHECK_READINESS_DROPS: SEVERITY_HIGH,
    CHECK_DEGRADED_HTTP_200S: SEVERITY_MEDIUM,
}

_READINESS_KEYS = ("status", "ready", "issues", "checked_at")
_DEGRADED_FLAG_SUFFIX = "_degraded"
_AUTO_COMPARE_PATHS = (
    "summary.total_subnets",
    "total_subnets",
    "graded",
    "learning.graded",
    "accuracy_lift.graded_7d",
)


@dataclass(frozen=True)
class SourceAttribution:
    """Policy §4.1 source attribution for one observed field."""

    field: str
    source: str


@dataclass(frozen=True)
class ObservedPayload:
    """One already-collected observation. Drift QA never fetches this itself."""

    name: str
    source: str = "unknown"
    freshness_source: Optional[str] = None
    http_status: Optional[int] = None
    body: Optional[Mapping[str, Any]] = None
    expected_keys: Tuple[str, ...] = ()
    expected_types: Tuple[Tuple[str, str], ...] = ()
    captured_at: Optional[str] = None
    labeled_live: bool = False
    hydration_ok: Optional[bool] = None
    ssr_keys: Tuple[str, ...] = ()
    client_keys: Tuple[str, ...] = ()
    loading: bool = False
    loading_seconds: Optional[float] = None
    loading_timeout_seconds: float = STUCK_PANEL_TIMEOUT_SECONDS
    panel: Optional[str] = None
    prior_body: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class DisagreementPair:
    left_name: str
    right_name: str
    fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DriftSnapshot:
    payloads: Tuple[ObservedPayload, ...] = ()
    pairs: Tuple[DisagreementPair, ...] = ()
    now: Optional[datetime] = None


def _empty_map() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class CheckResult:
    name: str
    flagged: bool
    severity: str
    evidence_class: str
    summary: str
    details: Tuple[str, ...] = ()
    attributions: Tuple[SourceAttribution, ...] = ()
    freshness: Mapping[str, Any] = field(default_factory=_empty_map)
    freshness_disclosure: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "flagged": self.flagged,
            "severity": self.severity,
            "evidence_class": self.evidence_class,
            "summary": self.summary,
            "details": list(self.details),
            "attributions": [
                {"field": item.field, "source": item.source} for item in self.attributions
            ],
            "freshness": _thaw(self.freshness),
            "freshness_disclosure": self.freshness_disclosure,
        }


@dataclass(frozen=True)
class Contradiction:
    tag: str
    left: str
    right: str
    detail: str
    freshness: Mapping[str, Any] = field(default_factory=_empty_map)
    freshness_disclosure: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "left": self.left,
            "right": self.right,
            "detail": self.detail,
            "freshness": _thaw(self.freshness),
            "freshness_disclosure": self.freshness_disclosure,
        }


@dataclass(frozen=True)
class EvidenceItem:
    """One attributed row inside an evidence bundle (Proof Scout ``relation``)."""

    relation: str
    summary: str
    freshness: Mapping[str, Any]
    freshness_disclosure: str
    attribution: Mapping[str, Any]
    payload: Mapping[str, Any] = field(default_factory=_empty_map)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation": self.relation,
            "summary": self.summary,
            "freshness": _thaw(self.freshness),
            "freshness_disclosure": self.freshness_disclosure,
            "attribution": _thaw(self.attribution),
            "payload": _thaw(self.payload),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """Policy §4 bundle for significant drift. Supporting vs contradictory."""

    subject: str
    check: str
    severity: str
    items: Tuple[EvidenceItem, ...]
    freshness: Mapping[str, Any]
    freshness_disclosure: str

    @property
    def supporting(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == EVIDENCE_SUPPORTING)

    @property
    def contradictory(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == EVIDENCE_CONTRADICTORY)

    @property
    def observations(self) -> Tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.relation == EVIDENCE_OBSERVATION)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "check": self.check,
            "severity": self.severity,
            "items": [item.to_dict() for item in self.items],
            "supporting": [item.to_dict() for item in self.supporting],
            "contradictory": [item.to_dict() for item in self.contradictory],
            "observations": [item.to_dict() for item in self.observations],
            "freshness": _thaw(self.freshness),
            "freshness_disclosure": self.freshness_disclosure,
        }


@dataclass(frozen=True)
class DriftReport:
    bot: str
    run_id: str
    status: str
    summary: str
    checks: Tuple[CheckResult, ...]
    contradictions: Tuple[Contradiction, ...]
    evidence_bundles: Tuple[EvidenceBundle, ...]
    freshness: Mapping[str, Any]
    freshness_disclosure: str
    observations: Tuple[str, ...]
    unknowns: Tuple[str, ...]
    confidence: Optional[float]
    recommended_action: Optional[str]
    approval_required: bool
    approval: Mapping[str, Any]
    audit: Mapping[str, Any]

    @property
    def findings(self) -> Tuple[CheckResult, ...]:
        return self.checks

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot": self.bot,
            "run_id": self.run_id,
            "status": self.status,
            "summary": self.summary,
            "checks": [item.to_dict() for item in self.checks],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "evidence_bundles": [item.to_dict() for item in self.evidence_bundles],
            "freshness": _thaw(self.freshness),
            "freshness_disclosure": self.freshness_disclosure,
            "observations": list(self.observations),
            "unknowns": list(self.unknowns),
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "approval_required": self.approval_required,
            "approval": _thaw(self.approval),
            "audit": _thaw(self.audit),
        }


def classify_evidence(
    *,
    flagged: bool,
    unavailable: bool = False,
    contradicts: bool = False,
) -> str:
    """Policy §4 evidence class. Missing sources stay unavailable, never inferred."""
    if unavailable:
        return EVIDENCE_UNAVAILABLE
    if flagged or contradicts:
        return EVIDENCE_CONTRADICTORY
    return EVIDENCE_SUPPORTING


def classify_severity(value: str) -> str:
    """Policy §3.1. Unknown labels are not a fifth class — fail closed."""
    label = str(value or "").strip().lower()
    if label not in _RISK_ORDER:
        return SEVERITY_CRITICAL
    return label


def severity_for_check(
    check_name: str,
    *,
    flagged: bool,
    unavailable: bool = False,
) -> str:
    """Map one drift check onto Policy §3.1.

    Unobserved/unavailable stays low (honest empty, not a finding). Body-gone
    while a schema was supplied is medium. Flagged drift uses ``_FLAGGED_SEVERITY``.
    """
    if not flagged:
        return SEVERITY_LOW
    if unavailable:
        return SEVERITY_MEDIUM
    return classify_severity(_FLAGGED_SEVERITY.get(check_name, SEVERITY_CRITICAL))


def _freeze(value: Any) -> Any:
    """Deep-freeze mappings so callers cannot mutate a returned report."""
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def format_age_seconds(age: Any) -> Optional[str]:
    """Render age as ``6m23s`` (Policy §2.3 example form)."""
    if age is None:
        return None
    try:
        total = int(round(float(age)))
    except (TypeError, ValueError):
        return None
    total = max(0, total)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes}m{seconds}s"
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def freshness_disclosure(envelope: Mapping[str, Any]) -> str:
    """Policy §2.3 user-facing line. Required on every claim, including fresh."""
    status = str(envelope.get("status") or "missing")
    source = envelope.get("source")
    age = envelope.get("age_seconds")
    nested = envelope.get("sources")
    if source is None and isinstance(nested, (list, tuple)) and nested:
        def _rank(item: Mapping[str, Any]) -> int:
            return _FRESHNESS_RANK.get(str(item.get("status")), 4)

        worst = max(
            (item for item in nested if isinstance(item, Mapping)),
            key=_rank,
            default=None,
        )
        if worst is not None:
            source = worst.get("source")
            if age is None:
                age = worst.get("age_seconds")
            if not envelope.get("status"):
                status = str(worst.get("status") or "missing")
    source_label = str(source or "unknown").replace("_", "-")
    age_label = format_age_seconds(age)
    if age_label is None:
        age_label = "age unknown"
    line = f"Evidence freshness: {source_label} is {status} ({age_label})."
    if status != "fresh":
        line += " Degraded confidence."
    return line


_FRESHNESS_RANK = {"fresh": 0, "aging": 1, "stale": 2, "missing": 3, "degraded": 4}


def _payload_degraded(payload: ObservedPayload) -> bool:
    if payload.http_status is not None and payload.http_status != 200:
        return True
    if payload.body is None:
        # Null HTTP/live bodies are untrusted. Panel-only observations (no HTTP,
        # no live label, no timestamp) stay missing rather than degraded.
        return (
            payload.http_status is not None
            or payload.labeled_live
            or payload.captured_at is not None
        )
    if isinstance(payload.body, Mapping) and _degraded_markers(payload.body):
        return True
    return False


def payload_envelope(
    payload: ObservedPayload,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """§2.2/§2.3 envelope for one already-collected payload."""
    source = payload.freshness_source or payload.source or "unknown"
    return classify_freshness(
        source,
        payload.captured_at,
        now=now,
        degraded=_payload_degraded(payload),
        authoritative=not str(source).endswith("archive"),
        mode="archive" if str(source).endswith("archive") else None,
    )


def _missing_envelope(*, now: Optional[datetime] = None, source: str = "unknown") -> Dict[str, Any]:
    return classify_freshness(source, None, now=now)


def _freshness_for_check(
    check: CheckResult,
    payloads: Sequence[ObservedPayload],
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Mapping[str, Any]:
    if check.evidence_class == EVIDENCE_UNAVAILABLE and not check.flagged:
        source = check.attributions[0].source if check.attributions else "unknown"
        return _missing_envelope(now=now, source=source)
    matched: list[Mapping[str, Any]] = []
    details = " ".join(check.details)
    attr_sources = {attr.source for attr in check.attributions}
    for payload in payloads:
        env = envelopes.get(payload.name)
        if env is None:
            continue
        if payload.name in details or payload.source in attr_sources:
            matched.append(env)
    if not matched:
        matched = [envelopes[payload.name] for payload in payloads if payload.name in envelopes]
    if not matched:
        attr_source = check.attributions[0].source if check.attributions else "unknown"
        return _missing_envelope(now=now, source=attr_source)
    if len(matched) == 1:
        return dict(matched[0])
    return aggregate_freshness(matched)


def _stamp_check(
    check: CheckResult,
    payloads: Sequence[ObservedPayload],
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> CheckResult:
    freshness = _freeze(_freshness_for_check(check, payloads, envelopes, now=now))
    unavailable = check.evidence_class == EVIDENCE_UNAVAILABLE
    return CheckResult(
        name=check.name,
        flagged=check.flagged,
        severity=severity_for_check(
            check.name, flagged=check.flagged, unavailable=unavailable
        ),
        evidence_class=check.evidence_class,
        summary=check.summary,
        details=check.details,
        attributions=check.attributions,
        freshness=freshness,
        freshness_disclosure=freshness_disclosure(freshness),
    )


def _stamp_contradiction(
    item: Contradiction,
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Contradiction:
    picked: list[Mapping[str, Any]] = []
    for key in (item.left, item.right):
        name = str(key).split(".", 1)[0].split(" ", 1)[0]
        if name in envelopes:
            picked.append(envelopes[name])
        else:
            for env_name, env in envelopes.items():
                if env_name in str(key) or str(key).startswith(env_name):
                    picked.append(env)
                    break
    if not picked:
        freshness = _freeze(_missing_envelope(now=now, source="contradiction"))
    elif len(picked) == 1:
        freshness = _freeze(dict(picked[0]))
    else:
        freshness = _freeze(aggregate_freshness(picked))
    return Contradiction(
        tag=item.tag,
        left=item.left,
        right=item.right,
        detail=item.detail,
        freshness=freshness,
        freshness_disclosure=freshness_disclosure(freshness),
    )


def _significant(check: CheckResult) -> bool:
    return bool(check.flagged) and _RISK_ORDER.get(check.severity, 0) >= _RISK_ORDER[SEVERITY_MEDIUM]


def _item_from(
    *,
    relation: str,
    summary: str,
    freshness: Mapping[str, Any],
    field_name: str,
    source: str,
    payload: Optional[Mapping[str, Any]] = None,
) -> EvidenceItem:
    frozen = _freeze(dict(freshness))
    return EvidenceItem(
        relation=relation,
        summary=summary,
        freshness=frozen,
        freshness_disclosure=freshness_disclosure(frozen),
        attribution=_freeze({"field": field_name, "source": source}),
        payload=_freeze(dict(payload or {})),
    )


def evidence_bundle_for(
    check: CheckResult,
    payloads: Sequence[ObservedPayload],
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> EvidenceBundle:
    """Build a §4 bundle: schema/prior as supporting, drift details as contradictory."""
    items: list[EvidenceItem] = []
    fallback = dict(check.freshness) or _missing_envelope(now=now, source=check.name)
    mentioned = " ".join(check.details)
    for payload in payloads:
        env = envelopes.get(payload.name) or fallback
        if payload.name in mentioned or any(
            payload.name in detail or payload.source in detail for detail in check.details
        ):
            continue
        items.append(
            _item_from(
                relation=EVIDENCE_SUPPORTING,
                summary=f"{payload.name} consistent with {check.name} contract",
                freshness=env,
                field_name=payload.panel or "body",
                source=payload.source,
                payload={"name": payload.name, "http_status": payload.http_status},
            )
        )
    if not any(item.relation == EVIDENCE_SUPPORTING for item in items):
        schema_source = (
            check.attributions[0].source if check.attributions else "schema"
        )
        items.append(
            _item_from(
                relation=EVIDENCE_SUPPORTING,
                summary=f"expected contract for {check.name}",
                freshness=fallback,
                field_name="schema",
                source=schema_source,
            )
        )
    for detail in check.details:
        relation = (
            EVIDENCE_OBSERVATION
            if detail.startswith("WARNING:")
            else EVIDENCE_CONTRADICTORY
        )
        source = "snapshot"
        env: Mapping[str, Any] = fallback
        for payload in payloads:
            if payload.name in detail or payload.source in detail:
                source = payload.source
                env = envelopes.get(payload.name) or fallback
                break
        items.append(
            _item_from(
                relation=relation,
                summary=detail,
                freshness=env,
                field_name=check.name,
                source=source,
            )
        )
    frozen_freshness = _freeze(dict(check.freshness) or fallback)
    return EvidenceBundle(
        subject=check.name,
        check=check.name,
        severity=check.severity,
        items=tuple(items),
        freshness=frozen_freshness,
        freshness_disclosure=check.freshness_disclosure or freshness_disclosure(frozen_freshness),
    )


def _dig(body: Optional[Mapping[str, Any]], path: str) -> Any:
    if not isinstance(body, Mapping) or not path:
        return _MISSING
    current: Any = body
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


class _Missing:
    pass


_MISSING = _Missing()


def _attr(payload: ObservedPayload, field_name: str) -> SourceAttribution:
    return SourceAttribution(field=field_name, source=payload.source)


def missing_required_fields(
    payloads: Sequence[ObservedPayload],
) -> CheckResult:
    missing: list[str] = []
    attributions: list[SourceAttribution] = []
    unavailable = False
    saw_schema = False
    for payload in payloads:
        if not payload.expected_keys:
            continue
        saw_schema = True
        attributions.append(_attr(payload, "body"))
        if payload.body is None:
            unavailable = True
            missing.append(f"WARNING: source unavailable: {payload.name} body")
            continue
        if not isinstance(payload.body, Mapping):
            missing.append(f"{payload.name}: body is not an object")
            continue
        absent = [key for key in payload.expected_keys if key not in payload.body]
        if absent:
            missing.append(f"{payload.name}: missing {', '.join(absent)}")
    if not saw_schema:
        return CheckResult(
            name=CHECK_MISSING_FIELDS,
            flagged=False,
            severity=SEVERITY_LOW,
            evidence_class=EVIDENCE_UNAVAILABLE,
            summary="No field schema supplied",
            details=("WARNING: source unavailable: schema",),
            attributions=(SourceAttribution(field="schema", source="not_supplied"),),
        )
    flagged = bool(missing)
    return CheckResult(
        name=CHECK_MISSING_FIELDS,
        flagged=flagged,
        severity=SEVERITY_HIGH if flagged and not unavailable else (
            SEVERITY_MEDIUM if unavailable else SEVERITY_LOW
        ),
        evidence_class=classify_evidence(flagged=flagged, unavailable=unavailable),
        summary="Required fields missing" if flagged else "Required fields present",
        details=tuple(missing),
        attributions=tuple(attributions),
    )


def api_shape_changed(
    payloads: Sequence[ObservedPayload],
) -> Tuple[CheckResult, Tuple[Contradiction, ...]]:
    changes: list[str] = []
    contradictions: list[Contradiction] = []
    attributions: list[SourceAttribution] = []
    unavailable = False
    saw_schema = False
    for payload in payloads:
        expected = payload.expected_keys or tuple(key for key, _ in payload.expected_types)
        if not expected and not payload.expected_types:
            continue
        saw_schema = True
        attributions.append(_attr(payload, "shape"))
        if payload.body is None:
            unavailable = True
            changes.append(f"WARNING: source unavailable: {payload.name} body")
            continue
        if not isinstance(payload.body, Mapping):
            changes.append(f"{payload.name}: expected object, got {type(payload.body).__name__}")
            contradictions.append(
                Contradiction(
                    TAG_SHAPE_VS_SCHEMA,
                    payload.name,
                    "schema",
                    f"body type {type(payload.body).__name__}",
                )
            )
            continue
        extra = [key for key in payload.body.keys() if expected and key not in expected]
        if extra:
            changes.append(f"{payload.name}: unexpected keys {', '.join(extra)}")
            contradictions.append(
                Contradiction(
                    TAG_SHAPE_VS_SCHEMA,
                    payload.name,
                    "schema",
                    f"unexpected keys {', '.join(extra)}",
                )
            )
        type_map = dict(payload.expected_types)
        for key, type_name in type_map.items():
            if key not in payload.body:
                continue
            value = payload.body[key]
            actual = type(value).__name__
            if actual != type_name and not (
                type_name == "int" and actual == "float"
            ):
                changes.append(f"{payload.name}.{key}: expected {type_name}, got {actual}")
                contradictions.append(
                    Contradiction(
                        TAG_SHAPE_VS_SCHEMA,
                        f"{payload.name}.{key}",
                        type_name,
                        f"got {actual}",
                    )
                )
    if not saw_schema:
        return (
            CheckResult(
                name=CHECK_SHAPE_CHANGES,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="No shape schema supplied",
                details=("WARNING: source unavailable: schema",),
                attributions=(SourceAttribution(field="schema", source="not_supplied"),),
            ),
            (),
        )
    flagged = bool(changes)
    return (
        CheckResult(
            name=CHECK_SHAPE_CHANGES,
            flagged=flagged,
            severity=SEVERITY_HIGH if flagged and not unavailable else (
                SEVERITY_MEDIUM if unavailable else SEVERITY_LOW
            ),
            evidence_class=classify_evidence(flagged=flagged, unavailable=unavailable),
            summary="API shape differs from expected schema" if flagged else "API shape matches schema",
            details=tuple(changes),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
    )


def hydration_failed(
    payloads: Sequence[ObservedPayload],
) -> Tuple[CheckResult, Tuple[Contradiction, ...]]:
    failures: list[str] = []
    contradictions: list[Contradiction] = []
    attributions: list[SourceAttribution] = []
    saw_any = False
    for payload in payloads:
        if (
            payload.hydration_ok is None
            and not payload.ssr_keys
            and not payload.client_keys
        ):
            continue
        saw_any = True
        attributions.append(_attr(payload, payload.panel or "hydration"))
        if payload.hydration_ok is False:
            failures.append(f"{payload.name}: hydration_ok=false")
        if payload.ssr_keys or payload.client_keys:
            ssr = set(payload.ssr_keys)
            client = set(payload.client_keys)
            if ssr != client:
                detail = (
                    f"{payload.name}: SSR keys {sorted(ssr)} != client keys {sorted(client)}"
                )
                failures.append(detail)
                contradictions.append(
                    Contradiction(TAG_SSR_VS_CLIENT, payload.name + ".ssr", payload.name + ".client", detail)
                )
    if not saw_any:
        return (
            CheckResult(
                name=CHECK_HYDRATION_FAILS,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="No hydration observations supplied",
                details=("WARNING: source unavailable: hydration",),
                attributions=(SourceAttribution(field="hydration", source="not_supplied"),),
            ),
            (),
        )
    flagged = bool(failures)
    return (
        CheckResult(
            name=CHECK_HYDRATION_FAILS,
            flagged=flagged,
            severity=SEVERITY_HIGH if flagged else SEVERITY_LOW,
            evidence_class=classify_evidence(flagged=flagged),
            summary="Hydration failed" if flagged else "Hydration observations look complete",
            details=tuple(failures),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
    )


def panel_stuck_loading(payloads: Sequence[ObservedPayload]) -> CheckResult:
    stuck: list[str] = []
    unknown: list[str] = []
    attributions: list[SourceAttribution] = []
    saw_any = False
    for payload in payloads:
        if not payload.loading and payload.loading_seconds is None:
            continue
        saw_any = True
        attributions.append(_attr(payload, payload.panel or "panel"))
        timeout = payload.loading_timeout_seconds or STUCK_PANEL_TIMEOUT_SECONDS
        elapsed = payload.loading_seconds
        if payload.loading and elapsed is not None and elapsed >= timeout:
            stuck.append(
                f"{payload.panel or payload.name}: loading {elapsed}s >= {timeout}s"
            )
        elif payload.loading and elapsed is None:
            unknown.append(
                f"WARNING: source unavailable: {payload.panel or payload.name} loading age"
            )
    if not saw_any:
        return CheckResult(
            name=CHECK_STUCK_PANELS,
            flagged=False,
            severity=SEVERITY_LOW,
            evidence_class=EVIDENCE_UNAVAILABLE,
            summary="No panel loading observations supplied",
            details=("WARNING: source unavailable: panels",),
            attributions=(SourceAttribution(field="panels", source="not_supplied"),),
        )
    flagged = bool(stuck)
    only_unknown = bool(unknown) and not flagged
    return CheckResult(
        name=CHECK_STUCK_PANELS,
        flagged=flagged,
        severity=SEVERITY_HIGH if flagged else SEVERITY_LOW,
        evidence_class=classify_evidence(flagged=flagged, unavailable=only_unknown),
        summary="Panel stuck in loading state" if flagged else "No stuck panels",
        details=tuple(stuck + unknown),
        attributions=tuple(attributions),
    )


def stale_data_labeled_live(
    payloads: Sequence[ObservedPayload],
    *,
    now: Optional[datetime] = None,
) -> Tuple[CheckResult, Tuple[Contradiction, ...], Tuple[Mapping[str, Any], ...]]:
    flags: list[str] = []
    contradictions: list[Contradiction] = []
    envelopes: list[Mapping[str, Any]] = []
    attributions: list[SourceAttribution] = []
    for payload in payloads:
        source = payload.freshness_source
        if (
            source is None
            and not payload.labeled_live
            and payload.captured_at is None
            and payload.http_status is None
            and payload.body is None
        ):
            continue
        envelope = payload_envelope(payload, now=now)
        envelopes.append(envelope)
        attributions.append(_attr(payload, "captured_at"))
        status = str(envelope.get("status"))
        if payload.labeled_live and status in {"stale", "missing", "degraded"}:
            detail = (
                f"{payload.name}: labeled live but freshness={status} "
                f"age_seconds={envelope.get('age_seconds')}"
            )
            flags.append(detail)
            contradictions.append(
                Contradiction(
                    TAG_LIVE_VS_FRESHNESS,
                    payload.name,
                    source,
                    detail,
                )
            )
    if not envelopes:
        return (
            CheckResult(
                name=CHECK_STALE_DATA,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="No freshness observations supplied",
                details=("WARNING: source unavailable: freshness",),
                attributions=(SourceAttribution(field="freshness", source="not_supplied"),),
            ),
            (),
            (),
        )
    flagged = bool(flags)
    return (
        CheckResult(
            name=CHECK_STALE_DATA,
            flagged=flagged,
            severity=SEVERITY_CRITICAL if flagged else SEVERITY_LOW,
            evidence_class=classify_evidence(flagged=flagged),
            summary="Stale data presented as live" if flagged else "Live labels match freshness",
            details=tuple(flags),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
        tuple(envelopes),
    )


def learning_totals_disagree(
    payloads: Sequence[ObservedPayload],
    pairs: Sequence[DisagreementPair],
) -> Tuple[CheckResult, Tuple[Contradiction, ...]]:
    by_name = {payload.name: payload for payload in payloads}
    flags: list[str] = []
    contradictions: list[Contradiction] = []
    attributions: list[SourceAttribution] = []
    if len(payloads) < 2 and not pairs:
        return (
            CheckResult(
                name=CHECK_DISAGREEMENT,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="Not enough sources to compare",
                details=("WARNING: source unavailable: disagreement pair",),
                attributions=(SourceAttribution(field="disagreement", source="not_supplied"),),
            ),
            (),
        )

    def compare(left: ObservedPayload, right: ObservedPayload, path: str) -> None:
        left_value = _dig(left.body, path)
        right_value = _dig(right.body, path)
        if left_value is _MISSING or right_value is _MISSING:
            return
        if left_value != right_value:
            detail = f"{left.name}.{path}={left_value!r} != {right.name}.{path}={right_value!r}"
            flags.append(detail)
            contradictions.append(
                Contradiction(TAG_SOURCES_DISAGREE, left.name, right.name, detail)
            )
            attributions.append(_attr(left, path))
            attributions.append(_attr(right, path))

    for pair in pairs:
        left = by_name.get(pair.left_name)
        right = by_name.get(pair.right_name)
        if left is None or right is None:
            flags.append(
                f"WARNING: source unavailable: pair {pair.left_name}/{pair.right_name}"
            )
            continue
        fields = pair.fields or _AUTO_COMPARE_PATHS
        for path in fields:
            compare(left, right, path)

    if not pairs:
        named = list(payloads)
        for index, left in enumerate(named):
            for right in named[index + 1 :]:
                for path in _AUTO_COMPARE_PATHS:
                    compare(left, right, path)

    unavailable = any(item.startswith("WARNING: source unavailable") for item in flags)
    flagged = any(not item.startswith("WARNING:") for item in flags)
    return (
        CheckResult(
            name=CHECK_DISAGREEMENT,
            flagged=flagged,
            severity=SEVERITY_HIGH if flagged else SEVERITY_LOW,
            evidence_class=classify_evidence(flagged=flagged, unavailable=unavailable and not flagged),
            summary="Sources disagree" if flagged else "No numeric/source disagreement",
            details=tuple(flags),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
    )


def readiness_drops(payloads: Sequence[ObservedPayload]) -> Tuple[CheckResult, Tuple[Contradiction, ...]]:
    flags: list[str] = []
    contradictions: list[Contradiction] = []
    attributions: list[SourceAttribution] = []
    saw_any = False
    for payload in payloads:
        looks_readiness = (
            "readiness" in payload.name
            or payload.freshness_source == "learning_health"
            or (isinstance(payload.body, Mapping) and "ready" in payload.body)
        )
        if not looks_readiness and payload.prior_body is None:
            continue
        saw_any = True
        attributions.append(_attr(payload, "readiness"))
        body = payload.body
        if body is None:
            flags.append(f"WARNING: source unavailable: {payload.name} readiness body")
            continue
        if not isinstance(body, Mapping):
            flags.append(f"{payload.name}: readiness body is not an object")
            continue
        dropped = [key for key in _READINESS_KEYS if key not in body]
        if dropped:
            flags.append(f"{payload.name}: dropped metadata {', '.join(dropped)}")
        status = str(body.get("status") or "").lower()
        ready = body.get("ready")
        if ready is False or status in {"degraded", "not_ready", "unready"}:
            flags.append(f"{payload.name}: ready={ready} status={status or 'missing'}")
        if isinstance(payload.prior_body, Mapping):
            prior_ready = payload.prior_body.get("ready")
            prior_status = str(payload.prior_body.get("status") or "").lower()
            was_ok = prior_ready is True or prior_status in {"ready", "ok", "success"}
            now_bad = ready is False or status in {"degraded", "not_ready", "unready"}
            if was_ok and now_bad:
                detail = f"{payload.name}: dropped from {prior_status or prior_ready} to {status or ready}"
                flags.append(detail)
                contradictions.append(
                    Contradiction(TAG_READINESS_VS_PRIOR, payload.name + ".prior", payload.name, detail)
                )
    if not saw_any:
        return (
            CheckResult(
                name=CHECK_READINESS_DROPS,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="No readiness observations supplied",
                details=("WARNING: source unavailable: readiness",),
                attributions=(SourceAttribution(field="readiness", source="not_supplied"),),
            ),
            (),
        )
    flagged = bool(flags)
    return (
        CheckResult(
            name=CHECK_READINESS_DROPS,
            flagged=flagged,
            severity=SEVERITY_HIGH if flagged else SEVERITY_LOW,
            evidence_class=classify_evidence(flagged=flagged),
            summary="Readiness dropped or metadata missing" if flagged else "Readiness metadata intact",
            details=tuple(flags),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
    )


def _degraded_markers(body: Mapping[str, Any]) -> Tuple[str, ...]:
    hits: list[str] = []
    status = str(body.get("status") or "").lower()
    if status == "degraded":
        hits.append("status=degraded")
    if "data" in body and body.get("data") is None:
        hits.append("data=null")
    for key, value in body.items():
        if key.endswith(_DEGRADED_FLAG_SUFFIX) and value is True:
            hits.append(f"{key}=true")
        if key in {"_degraded", "_proxy_degraded", "_blend_degraded"} and value is True:
            if f"{key}=true" not in hits:
                hits.append(f"{key}=true")
    return tuple(hits)


def http_200_contains_degraded_data(
    payloads: Sequence[ObservedPayload],
) -> Tuple[CheckResult, Tuple[Contradiction, ...]]:
    flags: list[str] = []
    contradictions: list[Contradiction] = []
    attributions: list[SourceAttribution] = []
    saw_http = False
    for payload in payloads:
        if payload.http_status is None:
            continue
        saw_http = True
        attributions.append(_attr(payload, "http_status"))
        if payload.http_status != 200:
            continue
        body = payload.body
        if body is None:
            flags.append(f"{payload.name}: HTTP 200 with data=null")
            contradictions.append(
                Contradiction(
                    TAG_HTTP_OK_VS_DEGRADED,
                    f"{payload.name} HTTP 200",
                    "payload",
                    "body is null",
                )
            )
            continue
        if not isinstance(body, Mapping):
            continue
        markers = _degraded_markers(body)
        if markers:
            detail = f"{payload.name}: HTTP 200 with {', '.join(markers)}"
            flags.append(detail)
            contradictions.append(
                Contradiction(TAG_HTTP_OK_VS_DEGRADED, f"{payload.name} HTTP 200", "payload", detail)
            )
    if not saw_http:
        return (
            CheckResult(
                name=CHECK_DEGRADED_HTTP_200S,
                flagged=False,
                severity=SEVERITY_LOW,
                evidence_class=EVIDENCE_UNAVAILABLE,
                summary="No HTTP observations supplied",
                details=("WARNING: source unavailable: http",),
                attributions=(SourceAttribution(field="http", source="not_supplied"),),
            ),
            (),
        )
    flagged = bool(flags)
    return (
        CheckResult(
            name=CHECK_DEGRADED_HTTP_200S,
            flagged=flagged,
            severity=SEVERITY_MEDIUM if flagged else SEVERITY_LOW,
            evidence_class=classify_evidence(flagged=flagged),
            summary="HTTP 200 carries a degraded payload" if flagged else "No degraded HTTP 200 payloads",
            details=tuple(flags),
            attributions=tuple(attributions),
        ),
        tuple(contradictions),
    )


def _log_report(report: DriftReport) -> None:
    from internal.ops.notify import notify

    flagged = [item.name for item in report.checks if item.flagged]
    payload = {
        "status": report.status,
        "flagged": flagged,
        "contradiction_count": len(report.contradictions),
        "bundle_count": len(report.evidence_bundles),
        "observation_only": True,
        "retries": 0,
        "mutations": 0,
        "freshness_disclosure": report.freshness_disclosure,
    }
    notify(
        "bot_observe",
        bot=BOT_NAME,
        run_id=report.run_id,
        status=report.status,
        flagged=flagged,
        contradiction_count=len(report.contradictions),
        observation_only=True,
        payload=payload,
    )
    for check in report.checks:
        notify(
            "observation",
            bot=BOT_NAME,
            run_id=report.run_id,
            observation_only=True,
            payload={
                "check": check.name,
                "flagged": check.flagged,
                "severity": check.severity,
                "summary": check.summary,
                "freshness_disclosure": check.freshness_disclosure,
            },
        )


def observe(snapshot: DriftSnapshot) -> DriftReport:
    """Run all eight checks once against a caller-supplied snapshot.

    Does not fetch, retry, write, or remediate. The only side effect is
    logging-only notify() calls.
    """
    payloads = snapshot.payloads
    now = snapshot.now
    envelope_map: Dict[str, Dict[str, Any]] = {
        payload.name: payload_envelope(payload, now=now) for payload in payloads
    }
    raw_checks: list[CheckResult] = []
    raw_contradictions: list[Contradiction] = []

    raw_checks.append(missing_required_fields(payloads))

    shape, shape_contra = api_shape_changed(payloads)
    raw_checks.append(shape)
    raw_contradictions.extend(shape_contra)

    hydrate, hydrate_contra = hydration_failed(payloads)
    raw_checks.append(hydrate)
    raw_contradictions.extend(hydrate_contra)

    raw_checks.append(panel_stuck_loading(payloads))

    stale, stale_contra, stale_envelopes = stale_data_labeled_live(payloads, now=now)
    raw_checks.append(stale)
    raw_contradictions.extend(stale_contra)

    disagree, disagree_contra = learning_totals_disagree(payloads, snapshot.pairs)
    raw_checks.append(disagree)
    raw_contradictions.extend(disagree_contra)

    ready, ready_contra = readiness_drops(payloads)
    raw_checks.append(ready)
    raw_contradictions.extend(ready_contra)

    degraded, degraded_contra = http_200_contains_degraded_data(payloads)
    raw_checks.append(degraded)
    raw_contradictions.extend(degraded_contra)

    checks = tuple(
        _stamp_check(item, payloads, envelope_map, now=now) for item in raw_checks
    )
    contradictions = tuple(
        _stamp_contradiction(item, envelope_map, now=now) for item in raw_contradictions
    )
    bundles = tuple(
        evidence_bundle_for(item, payloads, envelope_map, now=now)
        for item in checks
        if _significant(item)
    )

    flagged = [item for item in checks if item.flagged]
    unknowns = tuple(
        f"{item.summary} {item.freshness_disclosure}"
        for item in checks
        if item.evidence_class == EVIDENCE_UNAVAILABLE
    )
    if not payloads:
        status = "degraded"
        summary = "No observations supplied"
    elif flagged:
        status = "degraded"
        summary = f"{len(flagged)} drift check(s) flagged"
    else:
        status = "ok"
        summary = (
            f"No drift flagged; {len(unknowns)} check(s) unobserved"
            if unknowns
            else "No drift flagged"
        )
    contract_sources: Sequence[Mapping[str, Any]] = stale_envelopes or tuple(
        envelope_map.values()
    )
    contract = bot_contract(
        sources=contract_sources or None,
        source=(
            payloads[0].freshness_source or payloads[0].source
            if payloads
            else "unknown"
        ),
        confidence=None,
        state_changing=False,
        degraded=bool(flagged) or not payloads,
    )
    freshness = _freeze(contract["freshness"])
    report = DriftReport(
        bot=BOT_NAME,
        run_id=str(uuid.uuid4()),
        status=status,
        summary=summary,
        checks=checks,
        contradictions=contradictions,
        evidence_bundles=bundles,
        freshness=freshness,
        freshness_disclosure=freshness_disclosure(freshness),
        observations=tuple(
            f"{item.summary} {item.freshness_disclosure}" for item in flagged
        ),
        unknowns=unknowns,
        confidence=contract.get("confidence"),
        recommended_action=None,
        approval_required=False,
        approval=_freeze(contract["approval"]),
        audit=_freeze(
            {
                "sources_read": [payload.source for payload in payloads],
                "checks": list(CHECKS),
                "observation_only": True,
                "retries": 0,
                "mutations": 0,
            }
        ),
    )
    _log_report(report)
    return report
