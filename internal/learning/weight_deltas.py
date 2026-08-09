"""Recent council expert weight nudges for hero UI."""

from __future__ import annotations

from typing import Any, Dict, Optional

_CANONICAL = frozenset({"quant", "hype", "dark_horse", "technical"})
_JUDGES = frozenset({"oracle", "echo", "pulse"})


def _normalize_expert(raw: Any) -> str | None:
    name = str(raw or "").lower().strip().replace(" ", "_")
    if name == "darkhorse":
        name = "dark_horse"
    return name if name in _CANONICAL or name == "rogue" else None


_SKIP_GRADED_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def expert_graded_counts() -> Dict[str, int]:
    """Resolved prediction count per canonical expert (for honest Bench badges)."""
    counts = {name: 0 for name in _CANONICAL}
    try:
        from internal.learning.predictions_store import load_predictions
        from internal.council.expert_attribution import attribute_expert_for_row

        for pred in load_predictions().get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP_GRADED_OUTCOMES:
                continue
            if pred.get("correct") is None:
                continue
            expert = _normalize_expert(pred.get("expert"))
            if expert:
                counts[expert] = counts.get(expert, 0) + 1
                continue
            # Rogue bucket: rows that resolve to no canonical expert are counted
            # so the Rogue track record can earn a later promotion.
            if attribute_expert_for_row(pred) == "rogue":
                counts["rogue"] = counts.get("rogue", 0) + 1
    except Exception:
        pass
    return counts



# collect_trail_events returns oldest-first and truncates at limit, so a small
# window silently drops the newest weight_change rows. Scan a window wider than
# the persisted trail (capped at 200 rows) and walk it newest-first so the
# first delta seen per dial really is the latest.
_TRAIL_SCAN_LIMIT = 500


def collect_weight_trail_events(limit: int = _TRAIL_SCAN_LIMIT) -> list:
    """Trail rows for delta scans — collect once, reuse for expert + judge dials.

    ``collect_trail_events`` re-reads the soul map, the prediction ledger and the
    dev-signal trail on every call (seconds on a warm prod volume). Callers that
    need both dial families should collect once and pass the result in.
    """
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events
    except Exception:
        return []
    try:
        return collect_trail_events(limit)
    except Exception:
        return []


def recent_expert_weight_deltas(
    limit: int = _TRAIL_SCAN_LIMIT,
    events: Any = None,
) -> Dict[str, float]:
    """Latest nudge delta per expert from mindmap weight_change trail rows."""
    try:
        from internal.learning.trail_bus import normalize_event_type
    except Exception:
        return {}

    rows = events if isinstance(events, list) else collect_weight_trail_events(limit)
    out: Dict[str, float] = {}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        if normalize_event_type(row.get("event_type")) != "weight_change":
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        expert = _normalize_expert(row.get("judge") or evidence.get("dial"))
        if not expert or expert in out:
            continue
        try:
            out[expert] = round(float(evidence.get("delta")), 4)
        except (TypeError, ValueError):
            continue
    return out


def _normalize_judge(raw: Any) -> str | None:
    name = str(raw or "").lower().strip()
    return name if name in _JUDGES else None


def recent_judge_weight_deltas(
    limit: int = _TRAIL_SCAN_LIMIT,
    events: Any = None,
) -> Dict[str, float]:
    """Latest nudge delta per judge (oracle/echo/pulse) from weight_change trail."""
    try:
        from internal.learning.trail_bus import normalize_event_type
    except Exception:
        return {}

    rows = events if isinstance(events, list) else collect_weight_trail_events(limit)
    out: Dict[str, float] = {}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        if normalize_event_type(row.get("event_type")) != "weight_change":
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        judge = _normalize_judge(row.get("judge") or evidence.get("dial"))
        if not judge or judge in out:
            continue
        try:
            out[judge] = round(float(evidence.get("delta")), 4)
        except (TypeError, ValueError):
            continue
    return out

# ============ Rogue bucket tracking (weight-like %, promotion path) ============
# Promotion is RELATIVE to the incumbent council: an absolute bar (e.g. 55%)
# can sit above every real expert's observed hit rate and make promotion a
# de facto impossibility. Rogue earns its seat by beating the leading expert
# over a meaningful sample instead.
_ROGUE_PROMOTION_RULE = (
    "beats the leading council expert's hit rate (min 30 resolved rows)"
    " -> consider official expert"
)



def build_rogue_stats() -> Dict[str, Any]:
    """Track unresolved-attribution rows as a weight-like percentage.

    Rogue is tracked, never scored: it never enters expert_weights or pick
    generation, but its hit rate + volume decide whether it earns an official
    expert slot later (the promotion gate).
    """
    stats: Dict[str, Any] = {
        "count": 0,
        "share_pct": 0.0,
        "hit_rate": None,
        "tracked": True,
        "promotion_rule": _ROGUE_PROMOTION_RULE,
    }
    try:
        from internal.learning.predictions_store import load_predictions
        from internal.council.expert_attribution import attribute_expert_for_row

        total = 0
        hits = 0
        per_expert: Dict[str, list] = {name: [0, 0] for name in _CANONICAL}  # [graded, hits]
        for pred in load_predictions().get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP_GRADED_OUTCOMES:
                continue
            if pred.get("correct") is None:
                continue
            total += 1
            ok = bool(pred.get("correct"))
            expert = _normalize_expert(pred.get("expert"))
            if expert == "rogue" or (not expert and attribute_expert_for_row(pred) == "rogue"):
                stats["count"] += 1
                if ok:
                    hits += 1
            elif expert in per_expert:
                per_expert[expert][0] += 1
                if ok:
                    per_expert[expert][1] += 1
        if total:
            stats["share_pct"] = round(100.0 * stats["count"] / total, 1)
        if stats["count"]:
            stats["hit_rate"] = round(100.0 * hits / stats["count"], 1)
        rates = [
            100.0 * hit / graded
            for graded, hit in per_expert.values()
            if graded > 0
        ]
        if rates:
            best = max(rates)
            stats["council_best_hit_rate"] = round(best, 1)
            stats["council_avg_hit_rate"] = round(sum(rates) / len(rates), 1)
            # Relative bar: Rogue must beat the leading incumbent (not an
            # absolute 55% that may sit above every real expert's hit rate).
            stats["promotion_rule"] = (
                "hit_rate >= " + str(round(best, 1)) + "% (leading expert) and count >= 30"
                " -> consider official expert"
            )
    except Exception:
        pass
    return stats


def count_rogue_replay_rows(
    predictions_path: Optional[str] = None,
    *,
    include_archive: bool = True,
) -> Dict[str, int]:
    """Rows the weight replay now routes to Rogue instead of a real expert.

    Observability for the archive-hygiene fix (fix 3): archive rows whose only
    attribution is the legacy fallback stamp no longer nudge quant - they are
    skipped by the replay because Rogue is not a scored expert.
    """
    try:
        from internal.council.weights import merged_replay_rows
        from internal.council.signal_expert import expert_for_replay_row
    except Exception:
        return {"rogue": 0, "replayed": 0}
    try:
        rows, meta = merged_replay_rows(predictions_path, include_archive=include_archive)
        rogue = sum(1 for row in rows if expert_for_replay_row(row) == "rogue")
        return {"rogue": rogue, "replayed": len(rows), "total_graded": meta.get("total_graded", 0)}
    except Exception:
        return {"rogue": 0, "replayed": 0}
