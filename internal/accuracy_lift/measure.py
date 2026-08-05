"""Acc-1 shared accuracy measurement (read-only)."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from internal.accuracy_lift.populations import (
    is_council_trust_row,
    is_gradable_row,
    is_published_council_row,
    pick_source_bucket,
    population_of,
)
from internal.council.grading import direction_correct

NOISE_MAGNITUDE_PCT = 1.0


def _parse_utc_iso(ts: str) -> Optional[datetime]:
    try:
        raw = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {"predictions": data, "resolved": []}


def load_archive(path: str) -> Dict[str, Any]:
    """Load archive file or merge all files under a pre-epoch directory."""
    if os.path.isfile(path):
        return _load_json(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(path)

    merged: Dict[str, Any] = {"predictions": [], "resolved": []}
    names = sorted(
        entry
        for entry in os.listdir(path)
        if entry.startswith("pre-epoch-") and os.path.isfile(os.path.join(path, entry))
    )
    if not names:
        raise FileNotFoundError(f"no pre-epoch-* files in {path}")

    for name in names:
        blob = _load_json(os.path.join(path, name))
        merged["predictions"].extend(blob.get("predictions") or [])
        merged["resolved"].extend(blob.get("resolved") or [])
    merged["archive_files"] = names
    return merged


def iter_resolved(archive: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in ("resolved", "predictions"):
        for row in archive.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").lower()
            if bucket == "predictions" and status != "resolved":
                continue
            if row.get("actual_pct") is None and row.get("correct") is None:
                continue
            key = str(row.get("id") or f"{row.get('netuid')}-{row.get('created_at')}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def row_hit(row: Dict[str, Any]) -> Optional[bool]:
    if row.get("correct") is not None:
        return bool(row["correct"])
    outcome = str(row.get("outcome") or "").lower()
    if outcome == "hit":
        return True
    if outcome == "miss":
        return False
    actual = row.get("actual_pct")
    if actual is None:
        return None
    try:
        return direction_correct(row, float(actual))
    except (TypeError, ValueError):
        return None


def accuracy_stats(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    graded: List[bool] = []
    for row in rows:
        hit = row_hit(row)
        if hit is not None:
            graded.append(hit)
    total = len(graded)
    correct = sum(1 for hit in graded if hit)
    return {
        "n": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total, 4) if total else None,
    }


def _confidence(row: Dict[str, Any]) -> Optional[float]:
    for key in ("final_confidence", "pick_confidence", "confidence", "conviction"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
            return val / 100.0 if val > 1.0 else val
        except (TypeError, ValueError):
            continue
    return None


def _expert(row: Dict[str, Any]) -> str:
    from internal.council.expert_attribution import attribute_expert_for_row, normalize_expert

    expert = attribute_expert_for_row(row)
    if expert:
        return expert
    experts = row.get("experts_involved")
    if isinstance(experts, list) and experts:
        normalized = normalize_expert({"expert": experts[0]})
        if normalized:
            return normalized
    return "unknown"


def confidence_deciles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        conf = _confidence(row)
        if conf is None:
            label = "unknown"
        elif conf < 0.35:
            label = "0-35%"
        elif conf < 0.45:
            label = "35-45%"
        elif conf < 0.55:
            label = "45-55%"
        elif conf < 0.70:
            label = "55-70%"
        else:
            label = "70%+"
        buckets[label].append(row)
    order = ["0-35%", "35-45%", "45-55%", "55-70%", "70%+", "unknown"]
    return [{"bucket": label, **accuracy_stats(buckets[label])} for label in order if buckets[label]]


def grouped_accuracy(rows: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row) or "unknown")].append(row)
    out = []
    for label in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        out.append({"label": label, **accuracy_stats(groups[label])})
    return out


def magnitude_noise_share(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    misses = []
    for row in rows:
        hit = row_hit(row)
        if hit is not False:
            continue
        try:
            actual = abs(float(row.get("actual_pct") or 0))
        except (TypeError, ValueError):
            actual = 0.0
        misses.append(actual)
    if not misses:
        return {"misses": 0, "small_move_misses": 0, "share": None}
    small = sum(1 for actual in misses if actual < NOISE_MAGNITUDE_PCT)
    return {
        "misses": len(misses),
        "small_move_misses": small,
        "share": round(small / len(misses), 4),
    }


def horizon_compare(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_hours = grouped_accuracy(rows, lambda r: int(r.get("horizon_hours") or 0))
    h4 = next((g for g in by_hours if g["label"] == "4"), None)
    h24 = next((g for g in by_hours if g["label"] == "24"), None)
    verdict = "inconclusive"
    if h4 and h24 and h4.get("accuracy") is not None and h24.get("accuracy") is not None:
        if h24["accuracy"] > h4["accuracy"] + 0.02:
            verdict = "24h_better"
        elif h4["accuracy"] > h24["accuracy"] + 0.02:
            verdict = "4h_better"
        else:
            verdict = "similar"
    return {"by_horizon_hours": by_hours, "verdict": verdict, "h4": h4, "h24": h24}


def build_summary(rows: List[Dict[str, Any]], archive_path: str) -> Dict[str, Any]:
    overall = accuracy_stats(rows)
    published_rows = [row for row in rows if is_published_council_row(row)]
    horizon = horizon_compare(rows)
    noise = magnitude_noise_share(rows)
    experts = grouped_accuracy(rows, _expert)
    net_negative = [e for e in experts if e.get("n", 0) >= 5 and (e.get("accuracy") or 0) < 0.5]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "archive": archive_path,
        "overall": overall,
        "published_only": accuracy_stats(published_rows),
        "horizon_compare": horizon,
        "noise_misses": noise,
        "experts": experts,
        "net_negative_experts": net_negative,
        "confidence_deciles": confidence_deciles(rows),
        "pick_source": grouped_accuracy(rows, population_of),
        "phase_at_prediction": grouped_accuracy(rows, lambda r: r.get("phase_at_prediction") or "unknown"),
    }


def row_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    for key in ("resolved_at", "created_at", "graded_at"):
        raw = row.get(key)
        if raw:
            return _parse_utc_iso(str(raw))
    return None


def filter_window(rows: Iterable[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = row_timestamp(row)
        if ts is not None and ts >= cutoff:
            out.append(row)
    return out


def _by_expert_map(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_expert(row)].append(row)
    out: Dict[str, Dict[str, Any]] = {}
    for label, group_rows in groups.items():
        stats = accuracy_stats(group_rows)
        if stats["n"] <= 0:
            continue
        out[label] = {
            "graded": stats["n"],
            "hits": stats["correct"],
            "hit_rate": stats["accuracy"],
        }
    return out


_EMPTY_NOTE = "honest empty until graded>0"
_MIXED_NOTE = (
    "mixed ledger — includes HOLD/near-miss shadows + pump-desk claims; see published_only"
)


def _horizon_label(row: Dict[str, Any]) -> str:
    horizon_type = row.get("horizon_type")
    if horizon_type:
        return str(horizon_type)
    return f"{int(row.get('horizon_hours') or 0)}h"


def _graded_window_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in rows if row_hit(row) is not None]


def _published_block(
    w7_all: List[Dict[str, Any]],
    w30_all: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pub_w7 = [row for row in w7_all if is_published_council_row(row)]
    pub_w30 = [row for row in w30_all if is_published_council_row(row)]
    s7 = accuracy_stats(pub_w7)
    s30 = accuracy_stats(pub_w30)
    graded_7d = int(s7["n"])
    graded_30d = int(s30["n"])
    available = graded_7d > 0 or graded_30d > 0
    return {
        "data_available": available,
        "graded_7d": graded_7d,
        "graded_30d": graded_30d,
        "hit_rate_7d": s7["accuracy"],
        "hit_rate_30d": s30["accuracy"],
        "by_expert": _by_expert_map(pub_w30) if graded_30d > 0 else _by_expert_map(pub_w7),
        "note": None if available else _EMPTY_NOTE,
    }


def build_attribution_quality(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rolling attribution coverage for ops evidence."""
    total = len(rows)
    if total <= 0:
        return {"total": 0, "unknown": 0, "unknown_pct": None, "attributed": 0}
    unknown = sum(1 for row in rows if _expert(row) == "unknown")
    attributed = total - unknown
    return {
        "total": total,
        "unknown": unknown,
        "unknown_pct": round(unknown / total, 4),
        "attributed": attributed,
    }


def _window_actual_days(rows: List[Dict[str, Any]]) -> Optional[float]:
    timestamps = [ts for row in rows if (ts := row_timestamp(row)) is not None]
    if len(timestamps) < 2:
        return None
    span_days = (max(timestamps) - min(timestamps)).total_seconds() / 86400.0
    return round(span_days, 2)


def _population_rates(
    w7: List[Dict[str, Any]],
    w30: List[Dict[str, Any]],
    *,
    filter_fn: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    f7 = [row for row in w7 if filter_fn(row)]
    f30 = [row for row in w30 if filter_fn(row)]
    s7 = accuracy_stats(f7)
    s30 = accuracy_stats(f30)
    return {
        "graded_7d": int(s7["n"]),
        "hit_rate_7d": s7["accuracy"],
        "graded_30d": int(s30["n"]),
        "hit_rate_30d": s30["accuracy"],
    }


def _by_pick_source_map(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not is_gradable_row(row):
            continue
        groups[pick_source_bucket(row)].append(row)
    out: Dict[str, Dict[str, Any]] = {}
    for label in sorted(groups):
        stats = accuracy_stats(groups[label])
        out[label] = {
            "n": stats["n"],
            "correct": stats["correct"],
            "accuracy": stats["accuracy"],
        }
    return out


def _empty_accuracy_lift_snapshot() -> Dict[str, Any]:
    empty_rates = {
        "graded_7d": 0,
        "hit_rate_7d": None,
        "graded_30d": 0,
        "hit_rate_30d": None,
    }
    empty_attr = build_attribution_quality([])
    empty_published = _published_block([], [])
    return {
        "data_available": False,
        "population": "mixed_all_resolved",
        "graded_7d": 0,
        "graded_30d": 0,
        "hit_rate_7d": None,
        "hit_rate_30d": None,
        "by_expert": {},
        "attribution_quality": empty_attr,
        "published_only": empty_published,
        "council_trust": dict(empty_rates),
        "full_ledger": dict(empty_rates),
        "by_pick_source": {},
        "by_pick_source_30d": [],
        "by_horizon_30d": [],
        "window_actual_days": {"w7": None, "w30": None},
        "small_move_miss_share": {"misses": 0, "small_move_misses": 0, "share": None},
        "note": _EMPTY_NOTE,
    }


def build_accuracy_lift_snapshot(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Rolling 7d/30d read-only snapshot for ops evidence."""
    if rows is None:
        try:
            from internal.learning.predictions_store import load_predictions

            rows = iter_resolved(load_predictions())
        except Exception:
            rows = []

    w7_all = filter_window(rows, 7)
    w30_all = filter_window(rows, 30)
    mixed_7d = accuracy_stats(w7_all)
    mixed_30d = accuracy_stats(w30_all)
    graded_7d = int(mixed_7d["n"])
    graded_30d = int(mixed_30d["n"])
    published_only = _published_block(w7_all, w30_all)
    council_trust = _population_rates(w7_all, w30_all, filter_fn=is_council_trust_row)
    full_ledger = {
        "graded_7d": graded_7d,
        "hit_rate_7d": mixed_7d["accuracy"],
        "graded_30d": graded_30d,
        "hit_rate_30d": mixed_30d["accuracy"],
    }

    if graded_7d == 0 and graded_30d == 0:
        return _empty_accuracy_lift_snapshot()

    council_w7 = [row for row in w7_all if is_council_trust_row(row)]
    council_w30 = [row for row in w30_all if is_council_trust_row(row)]
    window_rows = w30_all if graded_30d > 0 else w7_all
    graded_w30 = _graded_window_rows(w30_all)

    return {
        "data_available": True,
        "population": "mixed_all_resolved",
        "graded_7d": graded_7d,
        "graded_30d": graded_30d,
        "hit_rate_7d": mixed_7d["accuracy"],
        "hit_rate_30d": mixed_30d["accuracy"],
        "by_expert": _by_expert_map(w30_all) if graded_30d > 0 else _by_expert_map(w7_all),
        "attribution_quality": build_attribution_quality(window_rows),
        "published_only": published_only,
        "council_trust": council_trust,
        "full_ledger": full_ledger,
        "by_pick_source": _by_pick_source_map(w30_all),
        "by_pick_source_30d": grouped_accuracy(graded_w30, population_of),
        "by_horizon_30d": grouped_accuracy(graded_w30, _horizon_label),
        "window_actual_days": {
            "w7": _window_actual_days(council_w7),
            "w30": _window_actual_days(council_w30),
        },
        "small_move_miss_share": magnitude_noise_share(council_w30),
        "note": _MIXED_NOTE,
    }

