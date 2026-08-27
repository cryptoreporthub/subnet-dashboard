"""Market Desk — read-only interpretive subnet-analysis specialist.

Phase 2 of the supervised SimiVision bot fleet
(``docs/simivision-evidence-bot-blueprint.md``).  Named Market Desk so it
does not collide with the existing Council Oracle role.

This module explains subnet movements and signal changes from existing
pump / signals / council / learning reads.  It does not override
SimiVision or Council, does not run a parallel prediction engine, and
does not mutate Soul-Map, learning records, registry, caches, or
deployment state.

Policy mapping (no numbered policy file is in-repo):
- §2.3 — source-specific freshness envelopes via ``internal.ops.bot_policy``
- §3.3 — observations, interpretations, and unknowns as distinct lists
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from internal.ops.bot_policy import (
    aggregate_freshness,
    approval_for,
    classify_freshness,
    with_bot_contract,
)

BOT = "market_desk"
_SUBJECT_RE = re.compile(r"(?i)\b(?:sn[\s-]*)?(\d{1,3})\b")


def analyze(
    subject: Any,
    *,
    now: Optional[datetime] = None,
    snapshots: Optional[Mapping[str, Any]] = None,
    proposed_action: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Read live + historical sources and return the specialist envelope.

    ``snapshots`` is an optional injected read model (tests / orchestrator).
    When omitted, this function reads persisted artifacts and never writes.
    """
    started = time.perf_counter()
    clock = now or datetime.now(timezone.utc)
    parsed = _parse_subject(subject)
    sources_read: List[str] = []
    collected = _collect(parsed.get("netuid"), snapshots, sources_read)
    if parsed.get("netuid") is None:
        parsed = _resolve_named_subject(parsed, collected)

    observations: List[Dict[str, Any]] = []
    interpretations: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    envelopes: List[Dict[str, Any]] = []

    live_row = _live_row(parsed.get("netuid"), collected)
    pump_row = _pump_row(parsed.get("netuid"), collected)
    signal_row = _signal_row(parsed.get("netuid"), collected)

    _add_pump_observations(
        parsed, pump_row, collected, clock, observations, evidence, envelopes, unknowns
    )
    _add_market_observations(
        parsed, live_row, collected, clock, observations, evidence, envelopes, unknowns
    )
    _add_signal_observations(
        parsed, signal_row, collected, clock, observations, evidence, envelopes, unknowns
    )
    _add_council_observations(
        parsed, collected, clock, observations, evidence, envelopes, unknowns
    )
    _add_learning_observations(
        parsed, collected, clock, observations, evidence, envelopes, unknowns
    )
    _add_message_intel_evidence(parsed, collected, clock, evidence, envelopes, unknowns)

    comparison = _comparison_report(live_row, pump_row, collected, observations)
    signal_change = _signal_change_explanation(
        pump_row, signal_row, live_row, collected, observations
    )
    _add_interpretations(
        parsed, live_row, pump_row, comparison, signal_change, observations, interpretations
    )

    current_envelopes = _current_claim_envelopes(envelopes, observations)
    freshness = aggregate_freshness(current_envelopes)
    freshness["sources"] = list(envelopes)
    if not current_envelopes:
        freshness["status"] = "missing"
        freshness["observed_at"] = None
        freshness["age_seconds"] = None

    observational_only = not interpretations
    raw_confidence = None if observational_only else _score_confidence(
        freshness_status=str(freshness.get("status") or "missing"),
        n_observations=len(observations),
        n_unknowns=len(unknowns),
        n_populations=len({item.get("population") for item in evidence if item.get("population")}),
    )
    uncertainty = None if observational_only else _uncertainty_range(
        raw_confidence, str(freshness.get("status") or "missing")
    )

    status = _status(parsed, freshness, observations, envelopes)
    summary = _plain_summary(
        parsed, observations, interpretations, unknowns, freshness, status, observational_only
    )
    approval_kwargs = _approval_kwargs(proposed_action)

    payload = {
        "bot": BOT,
        "run_id": uuid.uuid4().hex,
        "status": status,
        "subject": parsed.get("label") or str(subject or "").strip() or None,
        "summary": summary,
        "observations": observations,
        "interpretations": interpretations,
        "evidence": evidence,
        "unknowns": unknowns,
        "comparison": comparison,
        "signal_change": signal_change,
        "uncertainty": uncertainty,
        "recommended_action": None
        if not (proposed_action or {}).get("state_changing")
        else (proposed_action or {}).get("action"),
        "audit": {
            "sources_read": sources_read,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "writes": [],
        },
    }
    result = with_bot_contract(
        payload,
        sources=current_envelopes,
        confidence=raw_confidence,
        **approval_kwargs,
    )
    result["freshness"] = freshness
    return result


def report(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Public alias for ``analyze``."""
    return analyze(*args, **kwargs)


def _parse_subject(subject: Any) -> Dict[str, Any]:
    raw = "" if subject is None else str(subject).strip()
    if not raw:
        return {"raw": raw, "netuid": None, "label": None, "ok": False}
    match = _SUBJECT_RE.search(raw)
    if match:
        netuid = int(match.group(1))
        return {"raw": raw, "netuid": netuid, "label": f"SN{netuid}", "ok": True}
    return {"raw": raw, "netuid": None, "label": raw, "ok": True}


def _resolve_named_subject(
    parsed: Dict[str, Any], collected: Mapping[str, Any]
) -> Dict[str, Any]:
    name = str(parsed.get("raw") or "").strip().lower()
    if not name:
        return parsed
    for row in _iter_named_rows(collected):
        row_name = str(row.get("name") or "").strip().lower()
        if row_name and row_name == name:
            try:
                netuid = int(row.get("netuid"))
            except (TypeError, ValueError):
                continue
            resolved = dict(parsed)
            resolved["netuid"] = netuid
            resolved["label"] = f"SN{netuid}"
            return resolved
    return parsed


def _iter_named_rows(collected: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    live = collected.get("live_subnet")
    if isinstance(live, dict):
        yield live
    pump = _pump_row(None, collected)
    if pump:
        yield pump
    desk = collected.get("pump_desk") or {}
    for alert in desk.get("alerts") or []:
        if isinstance(alert, dict):
            yield alert


def _collect(
    netuid: Optional[int],
    snapshots: Optional[Mapping[str, Any]],
    sources_read: List[str],
) -> Dict[str, Any]:
    if snapshots is not None:
        sources_read.append("snapshots")
        return dict(snapshots)
    return _read_live(netuid, sources_read)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_live(netuid: Optional[int], sources_read: List[str]) -> Dict[str, Any]:
    collected: Dict[str, Any] = {}
    try:
        from internal.pump.state import load_state

        collected["pump_state"] = load_state()
        sources_read.append("internal.pump.state.load_state")
    except Exception:
        collected["pump_state"] = None
        sources_read.append("internal.pump.state.load_state:error")

    collected["pump_desk"] = _read_json(os.path.join("data", "pump_desk", "latest.json"))
    sources_read.append("data/pump_desk/latest.json")

    collected["signals"] = _read_json(os.path.join("data", "signals.json"))
    sources_read.append("data/signals.json")

    live_cache = _read_live_cache(netuid)
    collected["live_subnet"] = live_cache.get("subnet")
    collected["live_synced_at"] = live_cache.get("synced_at")
    sources_read.append("data/live_subnets.json")

    try:
        from internal.council.pick_history import get_history

        collected["council_history"] = get_history()
        sources_read.append("internal.council.pick_history.get_history")
    except Exception:
        collected["council_history"] = None
        sources_read.append("internal.council.pick_history.get_history:error")

    try:
        from internal.council.score_snapshots import load_score_snapshot

        collected["score_snapshot"] = load_score_snapshot()
        sources_read.append("internal.council.score_snapshots.load_score_snapshot")
    except Exception:
        collected["score_snapshot"] = None
        sources_read.append("internal.council.score_snapshots.load_score_snapshot:error")

    collected["learning_outcomes"] = _read_json(
        os.path.join("data", "learning_outcomes", "latest.json")
    )
    sources_read.append("data/learning_outcomes/latest.json")
    collected["predictions"] = _read_json(os.path.join("data", "predictions.json"))
    sources_read.append("data/predictions.json")
    return collected


def _read_live_cache(netuid: Optional[int]) -> Dict[str, Any]:
    try:
        from internal.live_subnets import _cache_path

        path = _cache_path()
    except Exception:
        path = os.path.join("data", "live_subnets.json")
    data = _read_json(path)
    if not data:
        return {}
    subnet = None
    if netuid is not None:
        for row in data.get("subnets") or []:
            if isinstance(row, dict) and _same_netuid(row.get("netuid"), netuid):
                subnet = row
                break
    return {"subnet": subnet, "synced_at": data.get("synced_at")}


def _same_netuid(value: Any, netuid: int) -> bool:
    try:
        return int(value) == int(netuid)
    except (TypeError, ValueError):
        return False


def _pump_row(netuid: Optional[int], collected: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    state = collected.get("pump_state") or {}
    subnets = state.get("subnets") if isinstance(state, dict) else None
    if isinstance(subnets, dict) and netuid is not None:
        row = subnets.get(str(netuid)) or subnets.get(netuid)
        if isinstance(row, dict):
            return row
    if isinstance(subnets, list) and netuid is not None:
        for row in subnets:
            if isinstance(row, dict) and _same_netuid(row.get("netuid"), netuid):
                return row
    desk = collected.get("pump_desk") or {}
    for alert in desk.get("alerts") or []:
        if isinstance(alert, dict) and netuid is not None and _same_netuid(alert.get("netuid"), netuid):
            return alert
    return None


def _live_row(netuid: Optional[int], collected: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    row = collected.get("live_subnet")
    if isinstance(row, dict):
        if netuid is None or _same_netuid(row.get("netuid"), netuid):
            return row
    return None


def _signal_row(netuid: Optional[int], collected: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    payload = collected.get("signals")
    if not isinstance(payload, dict) or netuid is None:
        return None
    latest = payload.get("latest_by_subnet") or {}
    if isinstance(latest, dict):
        row = latest.get(str(netuid)) or latest.get(netuid)
        if isinstance(row, dict):
            return row
    for entry in payload.get("entries") or []:
        if isinstance(entry, dict) and _same_netuid(
            entry.get("subnet_id") if entry.get("subnet_id") is not None else entry.get("netuid"),
            netuid,
        ):
            return entry
    return None


def _envelope(
    source: str,
    captured_at: Any,
    *,
    now: datetime,
    degraded: bool = False,
    mode: Optional[str] = None,
    authoritative: bool = True,
) -> Dict[str, Any]:
    return classify_freshness(
        source,
        captured_at,
        now=now,
        degraded=degraded,
        mode=mode,
        authoritative=authoritative,
    )


def _claim(
    kind: str,
    text: str,
    *,
    population: str,
    freshness: Mapping[str, Any],
    metric: Optional[str] = None,
    value: Any = None,
    based_on: Optional[List[str]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "id": f"{kind[:3]}-{uuid.uuid4().hex[:8]}",
        "kind": kind,
        "text": text,
        "population": population,
        "freshness": dict(freshness),
    }
    if metric is not None:
        item["metric"] = metric
    if value is not None:
        item["value"] = value
    if based_on:
        item["based_on"] = list(based_on)
    if extra:
        item.update(dict(extra))
    return item


def _evidence_item(
    *,
    population: str,
    source: str,
    freshness: Mapping[str, Any],
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    item = {
        "population": population,
        "source": source,
        "freshness": dict(freshness),
        "authoritative": freshness.get("authoritative", True),
        "claim_scope": freshness.get("claim_scope")
        or ("historical" if freshness.get("mode") == "archive" else "current"),
    }
    if ref:
        item["ref"] = ref
    return item


def _add_pump_observations(
    parsed: Dict[str, Any],
    pump_row: Optional[Dict[str, Any]],
    collected: Mapping[str, Any],
    now: datetime,
    observations: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    state = collected.get("pump_state") if isinstance(collected.get("pump_state"), dict) else {}
    desk = collected.get("pump_desk") if isinstance(collected.get("pump_desk"), dict) else {}
    captured = (
        (pump_row or {}).get("updated_at")
        or (state.get("meta") or {}).get("last_scan_at")
        or desk.get("captured_at")
    )
    degraded = bool(desk and str(desk.get("status") or "").lower() in {"error", "timeout"})
    env = _envelope("pump_desk", captured, now=now, degraded=degraded)
    envelopes.append(env)
    evidence.append(_evidence_item(population="pump", source="pump_desk", freshness=env, ref="pump_desk"))
    if not pump_row:
        unknowns.append(
            _claim(
                "unknown",
                f"No pump-ladder row for {parsed.get('label') or 'this subnet'}.",
                population="pump",
                freshness=env,
            )
        )
        return
    phase = pump_row.get("phase") or pump_row.get("current_phase")
    if phase:
        observations.append(
            _claim(
                "observation",
                f"Pump ladder phase is {phase}.",
                population="pump",
                freshness=env,
                metric="phase",
                value=phase,
            )
        )
    score = pump_row.get("composite_score")
    if score is not None:
        observations.append(
            _claim(
                "observation",
                f"Pump composite score is {float(score):.2f}.",
                population="pump",
                freshness=env,
                metric="composite_score",
                value=float(score),
            )
        )


def _add_market_observations(
    parsed: Dict[str, Any],
    live_row: Optional[Dict[str, Any]],
    collected: Mapping[str, Any],
    now: datetime,
    observations: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    captured = collected.get("live_synced_at") or (live_row or {}).get("updated_at")
    env = _envelope("market_data", captured, now=now)
    envelopes.append(env)
    evidence.append(
        _evidence_item(population="market_data", source="market_data", freshness=env, ref="live_subnets")
    )
    if not live_row:
        unknowns.append(
            _claim(
                "unknown",
                f"No live market row for {parsed.get('label') or 'this subnet'}.",
                population="market_data",
                freshness=env,
            )
        )
        return
    change = live_row.get("price_change_24h")
    if change is None:
        change = live_row.get("change_24h")
    if change is not None:
        observations.append(
            _claim(
                "observation",
                f"24h price change is {float(change):.4f}.",
                population="market_data",
                freshness=env,
                metric="price_change_24h",
                value=float(change),
            )
        )
    price = live_row.get("price")
    if price is not None:
        observations.append(
            _claim(
                "observation",
                f"Last observed price is {float(price)}.",
                population="market_data",
                freshness=env,
                metric="price",
                value=float(price),
            )
        )


def _add_signal_observations(
    parsed: Dict[str, Any],
    signal_row: Optional[Dict[str, Any]],
    collected: Mapping[str, Any],
    now: datetime,
    observations: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    payload = collected.get("signals") if isinstance(collected.get("signals"), dict) else {}
    captured = (signal_row or {}).get("timestamp") or payload.get("updated_at") or payload.get("refreshed_at")
    env = _envelope("market_data", captured, now=now)
    envelopes.append(env)
    evidence.append(_evidence_item(population="signals", source="market_data", freshness=env, ref="signals"))
    if not signal_row:
        unknowns.append(
            _claim(
                "unknown",
                f"No stored signal row for {parsed.get('label') or 'this subnet'}.",
                population="signals",
                freshness=env,
            )
        )
        return
    signal_type = signal_row.get("signal_type") or signal_row.get("type")
    if signal_type:
        observations.append(
            _claim(
                "observation",
                f"Stored signal type is {signal_type}.",
                population="signals",
                freshness=env,
                metric="signal_type",
                value=signal_type,
            )
        )


def _add_council_observations(
    parsed: Dict[str, Any],
    collected: Mapping[str, Any],
    now: datetime,
    observations: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    history = collected.get("council_history") if isinstance(collected.get("council_history"), dict) else {}
    snap = collected.get("score_snapshot") if isinstance(collected.get("score_snapshot"), dict) else {}
    captured = None
    active = history.get("active") if isinstance(history.get("active"), dict) else None
    if active:
        captured = active.get("created_at") or active.get("recorded_at")
    elif history.get("history"):
        first = history["history"][0]
        if isinstance(first, dict):
            captured = first.get("resolved_at") or first.get("created_at")
    hist_env = _envelope("pick_audit", captured, now=now)
    envelopes.append(hist_env)
    evidence.append(
        _evidence_item(population="council", source="pick_audit", freshness=hist_env, ref="pick_history")
    )
    netuid = parsed.get("netuid")
    match = None
    for row in [active] + list(history.get("history") or []):
        if isinstance(row, dict) and netuid is not None and _same_netuid(row.get("netuid"), netuid):
            match = row
            break
    if match:
        action = match.get("action") or match.get("outcome")
        observations.append(
            _claim(
                "observation",
                f"Council pick history records {action} for this subnet.",
                population="council",
                freshness=hist_env,
                metric="council_history",
                value=action,
            )
        )
    else:
        unknowns.append(
            _claim(
                "unknown",
                "No Council pick-history row for this subnet.",
                population="council",
                freshness=hist_env,
            )
        )

    snap_env = _envelope("learning_health", snap.get("written_at"), now=now)
    envelopes.append(snap_env)
    evidence.append(
        _evidence_item(
            population="council",
            source="learning_health",
            freshness=snap_env,
            ref="score_snapshots",
        )
    )
    score_row = None
    if netuid is not None:
        for row in snap.get("day") or []:
            if isinstance(row, dict) and _same_netuid(row.get("netuid"), netuid):
                score_row = row
                break
    if score_row and score_row.get("total_score") is not None:
        observations.append(
            _claim(
                "observation",
                f"Council day-score snapshot is {float(score_row['total_score']):.4f}.",
                population="council",
                freshness=snap_env,
                metric="day_score",
                value=float(score_row["total_score"]),
            )
        )
    elif not snap:
        unknowns.append(
            _claim(
                "unknown",
                "Council score snapshot is missing.",
                population="council",
                freshness=snap_env,
            )
        )


def _add_learning_observations(
    parsed: Dict[str, Any],
    collected: Mapping[str, Any],
    now: datetime,
    observations: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    from internal.learning.evidence import evidence_population, evidence_source

    outcomes = collected.get("learning_outcomes") if isinstance(collected.get("learning_outcomes"), dict) else {}
    predictions = collected.get("predictions") if isinstance(collected.get("predictions"), dict) else {}
    env = _envelope("learning_outcomes", outcomes.get("captured_at"), now=now)
    envelopes.append(env)
    evidence.append(
        _evidence_item(
            population="learning",
            source="learning_outcomes",
            freshness=env,
            ref="learning_outcomes",
        )
    )
    health = outcomes.get("council_health") if isinstance(outcomes.get("council_health"), dict) else {}
    if health:
        observations.append(
            _claim(
                "observation",
                (
                    "Learning outcomes council_health "
                    f"graded={health.get('graded')} correct={health.get('correct')}."
                ),
                population="learning",
                freshness=env,
                metric="council_health",
                value=health,
            )
        )
    netuid = parsed.get("netuid")
    archive_hit = None
    live_hit = None
    for bucket in ("predictions", "resolved"):
        for row in predictions.get(bucket) or []:
            if not isinstance(row, dict) or netuid is None or not _same_netuid(row.get("netuid"), netuid):
                continue
            population = evidence_population(row)
            source = evidence_source(row)
            if population == "archived" or source == "archive":
                archive_hit = row
            elif live_hit is None:
                live_hit = row
    if live_hit:
        observations.append(
            _claim(
                "observation",
                (
                    "Learning ledger has a "
                    f"{evidence_population(live_hit)} row with outcome "
                    f"{live_hit.get('outcome') or live_hit.get('status')}."
                ),
                population="learning",
                freshness=env,
                metric="learning_row",
                value=live_hit.get("outcome") or live_hit.get("status"),
            )
        )
    elif not health:
        unknowns.append(
            _claim(
                "unknown",
                "No learning-outcomes or ledger row for this subnet.",
                population="learning",
                freshness=env,
            )
        )
    if archive_hit:
        archive_captured = archive_hit.get("resolved_at") or archive_hit.get("created_at")
        archive_env = _envelope(
            "message_intel_archive",
            archive_captured or outcomes.get("captured_at"),
            now=now,
            mode="archive",
            authoritative=False,
        )
        envelopes.append(archive_env)
        evidence.append(
            _evidence_item(
                population="archive",
                source="message_intel_archive",
                freshness=archive_env,
                ref="predictions.archived",
            )
        )
        observations.append(
            _claim(
                "observation",
                "An archived learning row exists for this subnet (historical only).",
                population="archive",
                freshness=archive_env,
                metric="archived_row",
                extra={"claim_scope": "historical"},
            )
        )


def _add_message_intel_evidence(
    parsed: Dict[str, Any],
    collected: Mapping[str, Any],
    now: datetime,
    evidence: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
) -> None:
    payload = collected.get("message_intel") if isinstance(collected.get("message_intel"), dict) else {}
    if not payload:
        env = _envelope("message_intel_live", None, now=now)
        envelopes.append(env)
        evidence.append(
            _evidence_item(
                population="message_intel",
                source="message_intel_live",
                freshness=env,
                ref="message_intel",
            )
        )
        unknowns.append(
            _claim(
                "unknown",
                "No message-intel payload was supplied for this run.",
                population="message_intel",
                freshness=env,
            )
        )
        return
    mode = str(payload.get("mode") or "live")
    source = "message_intel_archive" if mode == "archive" else "message_intel_live"
    env = _envelope(
        source,
        payload.get("last_message_at") or payload.get("captured_at"),
        now=now,
        mode=mode,
        authoritative=mode != "archive",
    )
    envelopes.append(env)
    evidence.append(_evidence_item(population="message_intel", source=source, freshness=env))
    if parsed.get("netuid") is not None and payload.get("chatter") is None:
        unknowns.append(
            _claim(
                "unknown",
                "Message-intel chatter for this subnet is not available.",
                population="message_intel",
                freshness=env,
            )
        )


def _number(row: Optional[Mapping[str, Any]], *keys: str) -> Optional[float]:
    if not row:
        return None
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _comparison_report(
    live_row: Optional[Dict[str, Any]],
    pump_row: Optional[Dict[str, Any]],
    collected: Mapping[str, Any],
    observations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    current = {
        "price_change_24h": _number(live_row, "price_change_24h", "change_24h"),
        "price_change_7d": _number(live_row, "price_change_7d"),
        "phase": (pump_row or {}).get("phase") or (pump_row or {}).get("current_phase"),
        "composite_score": _number(pump_row, "composite_score"),
    }
    historical: Dict[str, Any] = {}
    transitions = list((pump_row or {}).get("transitions") or [])
    if transitions:
        last = transitions[-1] if isinstance(transitions[-1], dict) else {}
        historical["phase"] = last.get("from_phase")
        historical["composite_score"] = _number(last, "composite_score")
        historical["transition_time"] = last.get("time")
    outcomes = collected.get("learning_outcomes") if isinstance(collected.get("learning_outcomes"), dict) else {}
    health = outcomes.get("council_health") if isinstance(outcomes.get("council_health"), dict) else {}
    if health:
        historical["learning_graded"] = health.get("graded")
        historical["learning_correct"] = health.get("correct")
    deltas: List[Dict[str, Any]] = []
    if current.get("phase") and historical.get("phase") and current["phase"] != historical["phase"]:
        deltas.append(
            {
                "metric": "phase",
                "from": historical["phase"],
                "to": current["phase"],
            }
        )
    current_change = current.get("price_change_24h")
    weekly = current.get("price_change_7d")
    if current_change is not None and weekly is not None:
        deltas.append(
            {
                "metric": "price_change_24h_vs_7d_daily",
                "current": current_change,
                "historical_daily": round(weekly / 7.0, 6),
                "delta": round(current_change - (weekly / 7.0), 6),
            }
        )
    current_score = current.get("composite_score")
    prior_score = historical.get("composite_score")
    if current_score is not None and prior_score is not None:
        deltas.append(
            {
                "metric": "composite_score",
                "from": prior_score,
                "to": current_score,
                "delta": round(current_score - prior_score, 6),
            }
        )
    return {
        "current": current,
        "historical": historical,
        "deltas": deltas,
        "observation_ids": [item["id"] for item in observations if item.get("kind") == "observation"],
    }


def _signal_change_explanation(
    pump_row: Optional[Dict[str, Any]],
    signal_row: Optional[Dict[str, Any]],
    live_row: Optional[Dict[str, Any]],
    collected: Mapping[str, Any],
    observations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    transitions = [tx for tx in ((pump_row or {}).get("transitions") or []) if isinstance(tx, dict)]
    last = transitions[-1] if transitions else {}
    from_phase = last.get("from_phase")
    to_phase = last.get("to_phase") or (pump_row or {}).get("phase")
    changed = bool(from_phase and to_phase and from_phase != to_phase)
    drivers: List[str] = []
    signals = last.get("signals") if isinstance(last.get("signals"), dict) else {}
    for key in ("volume_intensity", "momentum_1h", "price_change_24h", "buy_ratio", "chatter_intensity"):
        if signals.get(key) is not None:
            drivers.append(f"{key}={signals.get(key)}")
    if signal_row and signal_row.get("signal_type"):
        drivers.append(f"stored_signal={signal_row.get('signal_type')}")
    if not drivers and live_row:
        change = _number(live_row, "price_change_24h", "change_24h")
        if change is not None:
            drivers.append(f"price_change_24h={change}")
    if changed:
        explanation = (
            f"The pump ladder moved {from_phase} → {to_phase}"
            + (f" with {', '.join(drivers[:3])}" if drivers else "")
            + ". This explains the observed signal change; it is not a new Council pick."
        )
    elif signal_row and signal_row.get("signal_type"):
        explanation = (
            f"No pump phase transition is on file; the stored signal remains "
            f"{signal_row.get('signal_type')}."
        )
    else:
        explanation = "No signal-change transition is available to explain."
    return {
        "changed": changed,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "drivers": drivers,
        "explanation": explanation,
        "observation_ids": [
            item["id"]
            for item in observations
            if item.get("population") in {"pump", "signals", "market_data"}
        ],
    }


def _add_interpretations(
    parsed: Dict[str, Any],
    live_row: Optional[Dict[str, Any]],
    pump_row: Optional[Dict[str, Any]],
    comparison: Mapping[str, Any],
    signal_change: Mapping[str, Any],
    observations: List[Dict[str, Any]],
    interpretations: List[Dict[str, Any]],
) -> None:
    obs_ids = [item["id"] for item in observations]
    supporting = [item["freshness"] for item in observations if item.get("freshness")]
    freshness = aggregate_freshness(supporting) if supporting else classify_freshness("market_data")
    if comparison.get("deltas"):
        delta_bits = []
        for delta in comparison["deltas"]:
            if delta.get("metric") == "phase":
                delta_bits.append(f"phase {delta.get('from')} → {delta.get('to')}")
            elif delta.get("metric") == "price_change_24h_vs_7d_daily":
                delta_bits.append(
                    "24h change vs 7d daily average "
                    f"({delta.get('current')} vs {delta.get('historical_daily')})"
                )
            elif delta.get("metric") == "composite_score":
                delta_bits.append(f"composite score delta {delta.get('delta')}")
        interpretations.append(
            _claim(
                "interpretation",
                (
                    f"{parsed.get('label') or 'This subnet'} current vs historical: "
                    + "; ".join(delta_bits)
                    + ". Inference only — not a guaranteed market conclusion."
                ),
                population="market_desk",
                freshness=freshness,
                based_on=obs_ids,
                extra={"capability": "comparison"},
            )
        )
    if signal_change.get("changed") or signal_change.get("drivers"):
        interpretations.append(
            _claim(
                "interpretation",
                str(signal_change.get("explanation")),
                population="market_desk",
                freshness=freshness,
                based_on=signal_change.get("observation_ids") or obs_ids,
                extra={"capability": "signal_change"},
            )
        )
    if live_row:
        try:
            from internal.council.recovery_context import build_recovery_context

            recovery = build_recovery_context(live_row)
        except Exception:
            recovery = None
        if recovery and recovery.get("classification") not in {None, "inconclusive"}:
            interpretations.append(
                _claim(
                    "interpretation",
                    (
                        "Recovery-context classification is "
                        f"{recovery.get('classification')} from existing market fields. "
                        "Market Desk does not override Council scoring."
                    ),
                    population="market_desk",
                    freshness=freshness,
                    based_on=obs_ids,
                    extra={"capability": "recovery_context", "recovery": recovery.get("classification")},
                )
            )


def _current_claim_envelopes(
    envelopes: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate freshness from observation envelopes, not unused siblings.

    Unused missing populations stay on ``freshness.sources`` and in ``unknowns``.
    Archive / non-authoritative envelopes never make a current claim fresh.
    """
    current: List[Dict[str, Any]] = []
    seen = set()
    for item in observations:
        env = item.get("freshness") or {}
        if not env:
            continue
        if env.get("claim_scope") == "historical" or env.get("authoritative") is False:
            continue
        key = (env.get("source"), env.get("captured_at"), env.get("status"))
        if key in seen:
            continue
        seen.add(key)
        current.append(dict(env))
    return current


def _score_confidence(
    *,
    freshness_status: str,
    n_observations: int,
    n_unknowns: int,
    n_populations: int,
) -> float:
    score = 0.30 + 0.08 * min(n_populations, 4) + 0.04 * min(n_observations, 5)
    if freshness_status == "fresh":
        score += 0.22
    elif freshness_status == "aging":
        score += 0.08
    elif freshness_status == "stale":
        score -= 0.20
    else:
        score -= 0.30
    score -= 0.04 * min(n_unknowns, 5)
    return round(score, 4)


def _uncertainty_range(confidence: Optional[float], freshness_status: str) -> Optional[Dict[str, float]]:
    if confidence is None:
        return None
    spread = {
        "fresh": 0.08,
        "aging": 0.16,
        "stale": 0.28,
        "missing": 0.36,
        "degraded": 0.36,
    }.get(freshness_status, 0.20)
    return {
        "low": round(max(0.0, float(confidence) - spread), 4),
        "high": round(min(1.0, float(confidence) + spread), 4),
    }


def _status(
    parsed: Dict[str, Any],
    freshness: Mapping[str, Any],
    observations: List[Dict[str, Any]],
    envelopes: List[Dict[str, Any]],
) -> str:
    if not parsed.get("ok"):
        return "blocked"
    if any(env.get("status") == "degraded" for env in envelopes):
        return "degraded"
    status = str(freshness.get("status") or "missing")
    if status in {"stale", "missing", "degraded"}:
        return "degraded"
    if not observations:
        return "degraded"
    return "ok"


def _plain_summary(
    parsed: Dict[str, Any],
    observations: List[Dict[str, Any]],
    interpretations: List[Dict[str, Any]],
    unknowns: List[Dict[str, Any]],
    freshness: Mapping[str, Any],
    status: str,
    observational_only: bool,
) -> str:
    label = parsed.get("label") or "This subnet"
    parts: List[str] = []
    obs_text = next((item["text"] for item in observations if item.get("population") == "pump"), None)
    if not obs_text and observations:
        obs_text = observations[0]["text"]
    if obs_text:
        parts.append(f"{label}: {obs_text.rstrip('.')} (observation).")
    else:
        parts.append(f"{label}: no current market observation is available.")
    if interpretations:
        parts.append(interpretations[0]["text"])
    elif observational_only:
        parts.append("No interpretation is offered on this run; the response is observational only.")
    freshness_status = freshness.get("status") or "missing"
    parts.append(
        f"Source freshness is {freshness_status} (status {status}); "
        "a stale source is not treated as a fresh conclusion."
    )
    if unknowns:
        parts.append(f"{len(unknowns)} unknown(s) remain, including {unknowns[0]['text']}")
    parts.append(
        "Market Desk does not override SimiVision or Council and does not issue "
        "guaranteed financial conclusions."
    )
    return " ".join(parts)


def _approval_kwargs(proposed_action: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    action = dict(proposed_action or {})
    state_changing = bool(action.get("state_changing"))
    category = action.get("action_category")
    if state_changing:
        approval = approval_for(category, state_changing=True)
        return {
            "state_changing": True,
            "action_category": approval.get("action_category"),
        }
    return {"state_changing": False}
