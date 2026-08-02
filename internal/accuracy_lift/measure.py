"""Acc-1 shared accuracy measurement (read-only)."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

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
    expert = row.get("expert")
    if isinstance(expert, str) and expert:
        return expert
    experts = row.get("experts_involved")
    if isinstance(experts, list) and experts:
        return str(experts[0])
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
    horizon = horizon_compare(rows)
    noise = magnitude_noise_share(rows)
    experts = grouped_accuracy(rows, _expert)
    net_negative = [e for e in experts if e.get("n", 0) >= 5 and (e.get("accuracy") or 0) < 0.5]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "archive": archive_path,
        "overall": overall,
        "horizon_compare": horizon,
        "noise_misses": noise,
        "experts": experts,
        "net_negative_experts": net_negative,
        "confidence_deciles": confidence_deciles(rows),
        "pick_source": grouped_accuracy(rows, lambda r: r.get("pick_source") or r.get("signal_source") or "unknown"),
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


def build_accuracy_lift_snapshot(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Rolling 7d/30d read-only snapshot for ops evidence."""
    if rows is None:
        try:
            from internal.learning.predictions_store import load_predictions

            rows = iter_resolved(load_predictions())
        except Exception:
            rows = []

    w7 = filter_window(rows, 7)
    w30 = filter_window(rows, 30)
    stats_7d = accuracy_stats(w7)
    stats_30d = accuracy_stats(w30)
    graded_7d = int(stats_7d["n"])
    graded_30d = int(stats_30d["n"])

    if graded_7d == 0 and graded_30d == 0:
        return {
            "data_available": False,
            "graded_7d": 0,
            "graded_30d": 0,
            "hit_rate_7d": None,
            "hit_rate_30d": None,
            "by_expert": {},
            "note": _EMPTY_NOTE,
        }

    return {
        "data_available": True,
        "graded_7d": graded_7d,
        "graded_30d": graded_30d,
        "hit_rate_7d": stats_7d["accuracy"],
        "hit_rate_30d": stats_30d["accuracy"],
        "by_expert": _by_expert_map(w30) if graded_30d > 0 else _by_expert_map(w7),
        "note": None,
    }

