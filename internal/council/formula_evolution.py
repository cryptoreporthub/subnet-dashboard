"""Formula evolution trail — time-bounded episodes of how a lane diverged and why.

Reconstructs narrative from:
  - learning_trail weight_change rows (soul_map)
  - resolved predictions for the lane's expert
  - calibration history (retrain → cert → fire)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.formula_lineage import LANE_IDS, build_lane_lineage
from internal.council.human_narrative import (
    calibration_episode_story,
    current_state_story,
    evolution_trail_summary,
    origin_story,
    subnet_window_story,
    version_nickname_story,
    weight_nudge_story,
)
from internal.council.lane_aliases import version_promotion
from internal.council.resolver import _normalize_expert
from internal.council.weights import DEFAULT_WEIGHTS, _load_raw, load_weights

_MIN_WINDOW_RESOLVES = 2
_SIGNIFICANT_ACC_SWING = 0.12
_SIGNIFICANT_WEIGHT_DELTA = 0.04
_EPISODE_SORT = {
    "subnet_divergence": 10,
    "weight_nudge": 20,
    "calibration": 30,
    "version_upgrade": 40,
    "version_nickname": 41,
}


def _parse_day(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    s = str(ts).strip()
    if len(s) >= 10:
        return s[:10]
    return None


def _lane_predictions(lane_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        from internal.learning.predictions_store import load_predictions

        for pred in load_predictions().get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("correct") is None:
                continue
            expert = _normalize_expert(pred)
            if expert != lane_id:
                continue
            rows.append(pred)
    except Exception:
        pass
    rows.sort(key=lambda r: str(r.get("resolved_at") or r.get("created_at") or ""))
    return rows


def _learning_trail_rows() -> List[Dict[str, Any]]:
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events

        return collect_trail_events(limit=500)
    except Exception:
        return []


def _weight_events(lane_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in _learning_trail_rows():
        et = str(row.get("event_type") or "").lower()
        judge = str(row.get("judge") or "").lower()
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        dial = str(evidence.get("dial") or evidence.get("expert") or judge).lower()
        if et != "weight_change" and "weight" not in str(row.get("signal") or "").lower():
            if dial != lane_id and judge != lane_id:
                continue
        if dial != lane_id and judge != lane_id:
            continue
        before = evidence.get("before")
        after = evidence.get("after")
        if before is None and after is None:
            continue
        out.append(
            {
                "time": row.get("time"),
                "day": _parse_day(row.get("time")),
                "before": before,
                "after": after,
                "delta": evidence.get("delta"),
                "reason": evidence.get("reason"),
                "correct": (row.get("extra") or {}).get("correct")
                if isinstance(row.get("extra"), dict)
                else evidence.get("correct"),
                "subnet": row.get("subnet"),
                "netuid": row.get("netuid"),
            }
        )
    out.sort(key=lambda r: str(r.get("time") or ""))
    return out


def _calibration_episodes() -> List[Dict[str, Any]]:
    data = _load_raw()
    adv = data.get("adversarial_state") if isinstance(data.get("adversarial_state"), dict) else {}
    cal = adv.get("calibration") if isinstance(adv.get("calibration"), dict) else {}
    episodes: List[Dict[str, Any]] = []
    for event in cal.get("history") or []:
        if not isinstance(event, dict):
            continue
        episodes.append(
            {
                "time": event.get("at"),
                "day": _parse_day(event.get("at")),
                "status": event.get("status"),
                "proposed_weights": event.get("proposed_weights"),
                "cert": event.get("cert"),
            }
        )
    return episodes


def _version_episodes(lane_id: str) -> List[Dict[str, Any]]:
    """Council weight version bumps from formula_versions history."""
    try:
        from internal.council.formula_versions import load_formula_versions

        versions = load_formula_versions()
    except Exception:
        return []
    council = versions.get("council_weights") if isinstance(versions.get("council_weights"), dict) else {}
    episodes: List[Dict[str, Any]] = []
    for entry in council.get("history") or []:
        if not isinstance(entry, dict):
            continue
        before = (entry.get("weights_before") or {}).get(lane_id)
        after = (entry.get("weights_after") or {}).get(lane_id)
        if before is None and after is None:
            continue
        if not entry.get("version_bumped"):
            continue
        day = _parse_day(entry.get("fired_at"))
        episodes.append(
            {
                "time": entry.get("fired_at"),
                "day": day,
                "version": entry.get("version"),
                "previous_version": entry.get("previous_version"),
                "beat_previous": entry.get("beat_previous"),
                "story": entry.get("story"),
                "before": before,
                "after": after,
            }
        )
    return episodes


def _subnet_trigger_row(pred: Dict[str, Any]) -> Dict[str, Any]:
    pred_pct = pred.get("predicted_pct")
    actual_pct = pred.get("actual_pct")
    direction = str(pred.get("direction") or "up")
    return {
        "name": pred.get("name") or f"SN{pred.get('netuid')}",
        "netuid": pred.get("netuid"),
        "predicted_pct": pred_pct,
        "actual_pct": actual_pct,
        "correct": pred.get("correct"),
        "expected_direction": direction,
        "signal_source": pred.get("signal_source"),
        "resolved_at": pred.get("resolved_at") or pred.get("created_at"),
        "statement": pred.get("statement"),
    }


def _daily_windows(preds: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pred in preds:
        day = _parse_day(pred.get("resolved_at") or pred.get("created_at"))
        if day:
            buckets[day].append(pred)
    return sorted(buckets.items())


def _accuracy(rows: List[Dict[str, Any]]) -> Optional[float]:
    if not rows:
        return None
    hits = sum(1 for r in rows if r.get("correct"))
    return round(hits / len(rows), 4)


def _divergence_pct(before: Optional[float], after: Optional[float]) -> Optional[float]:
    try:
        b, a = float(before), float(after)
    except (TypeError, ValueError):
        return None
    if b == 0:
        return None
    return round(abs(a - b) / abs(b) * 100.0, 1)


def build_evolution_trail(lane_id: str) -> Optional[Dict[str, Any]]:
    """Chronological episodes: origin → divergences → current state."""
    lane = build_lane_lineage(lane_id)
    if lane is None:
        return None

    lane_id = lane_id.lower().strip()
    label = lane["label"]
    formula = lane.get("current_formula") or {}
    preds = _lane_predictions(lane_id)
    weight_events = _weight_events(lane_id)
    cal_events = _calibration_episodes()
    version_events = _version_episodes(lane_id)

    episodes: List[Dict[str, Any]] = []

    first_day = _parse_day(preds[0].get("resolved_at") or preds[0].get("created_at")) if preds else None
    inspiration = (lane.get("inspiration") or [{}])[0]
    episodes.append(
        {
            "episode_id": "origin",
            "kind": "origin",
            "from": first_day,
            "to": first_day,
            "divergence_pct": 0.0,
            "formula_expression": formula.get("expression"),
            "inspiration_citation": inspiration.get("citation"),
            "inspiration_url": inspiration.get("url"),
            "weight_before": DEFAULT_WEIGHTS.get(lane_id, 1.0),
            "weight_after": DEFAULT_WEIGHTS.get(lane_id, 1.0),
            "trigger_subnets": [],
            "narrative": origin_story(
                label,
                inspiration.get("citation", ""),
                formula.get("expression", ""),
                DEFAULT_WEIGHTS.get(lane_id, 1.0),
            ),
        }
    )

    prev_acc: Optional[float] = None
    for day, bucket in _daily_windows(preds):
        if len(bucket) < _MIN_WINDOW_RESOLVES:
            continue
        acc = _accuracy(bucket)
        acc_delta = (acc - prev_acc) if acc is not None and prev_acc is not None else None
        prev_acc = acc
        if acc_delta is None or abs(acc_delta) < _SIGNIFICANT_ACC_SWING:
            continue
        wrong = [p for p in bucket if not p.get("correct")]
        triggers = [_subnet_trigger_row(p) for p in (wrong or bucket)[:3]]
        episodes.append(
            {
                "episode_id": f"window_{day}",
                "kind": "subnet_divergence",
                "from": day,
                "to": day,
                "divergence_pct": round(abs(acc_delta) * 100, 1),
                "accuracy_in_window": acc,
                "accuracy_delta_pp": round(acc_delta * 100, 1) if acc_delta is not None else None,
                "formula_expression": formula.get("expression"),
                "trigger_subnets": triggers,
                "narrative": subnet_window_story(
                    label, day, acc, acc_delta, triggers, len(bucket)
                ),
            }
        )

    for ev in weight_events:
        try:
            before = float(ev.get("before"))
            after = float(ev.get("after"))
        except (TypeError, ValueError):
            continue
        if abs(after - before) < _SIGNIFICANT_WEIGHT_DELTA:
            continue
        day = ev.get("day")
        episodes.append(
            {
                "episode_id": f"weight_{day}_{before}_{after}",
                "kind": "weight_nudge",
                "from": day,
                "to": day,
                "divergence_pct": _divergence_pct(before, after),
                "weight_before": before,
                "weight_after": after,
                "formula_expression": formula.get("expression"),
                "trigger_subnets": (
                    [_subnet_trigger_row({"name": ev.get("subnet"), "netuid": ev.get("netuid"), "correct": ev.get("correct")})]
                    if ev.get("subnet") or ev.get("netuid")
                    else []
                ),
                "narrative": weight_nudge_story(
                    label, day, before, after, ev.get("reason"), ev.get("subnet")
                ),
            }
        )

    for ver in version_events:
        try:
            before = float(ver.get("before"))
            after = float(ver.get("after"))
        except (TypeError, ValueError):
            continue
        day = ver.get("day")
        episodes.append(
            {
                "episode_id": f"version_{ver.get('version')}_{day}",
                "kind": "version_upgrade",
                "from": day,
                "to": day,
                "version": ver.get("version"),
                "previous_version": ver.get("previous_version"),
                "beat_previous": ver.get("beat_previous"),
                "divergence_pct": _divergence_pct(before, after),
                "weight_before": before,
                "weight_after": after,
                "formula_expression": formula.get("expression"),
                "trigger_subnets": [],
                "narrative": ver.get("story")
                or calibration_episode_story(
                    label, "fired", after, version=ver.get("version")
                ),
            }
        )
        promo = version_promotion(lane_id, str(ver.get("version") or ""), label)
        episodes.append(
            {
                "episode_id": f"nickname_{ver.get('version')}_{day}",
                "kind": "version_nickname",
                "from": day,
                "to": day,
                "version": ver.get("version"),
                "original_name": label,
                "nickname": promo["nickname"],
                "paper_title": promo.get("paper_title"),
                "paper_twist": promo.get("paper_twist"),
                "trigger_subnets": [],
                "narrative": version_nickname_story(
                    label,
                    promo["nickname"],
                    str(ver.get("version") or ""),
                    paper_title=promo.get("paper_title"),
                    paper_twist=promo.get("paper_twist"),
                ),
            }
        )

    for cal in cal_events:
        proposed = cal.get("proposed_weights") if isinstance(cal.get("proposed_weights"), dict) else {}
        if lane_id not in proposed:
            continue
        current_w = load_weights().get(lane_id)
        proposed_w = proposed.get(lane_id)
        status = cal.get("status")
        episodes.append(
            {
                "episode_id": f"calibration_{cal.get('day')}_{status}",
                "kind": "calibration",
                "from": cal.get("day"),
                "to": cal.get("day"),
                "divergence_pct": _divergence_pct(current_w, proposed_w),
                "weight_before": current_w,
                "weight_after": proposed_w,
                "calibration_status": status,
                "formula_expression": formula.get("expression"),
                "trigger_subnets": [],
                "narrative": calibration_episode_story(
                    label, status, proposed_w
                ),
            }
        )

    weights = load_weights()
    current_w = weights.get(lane_id) if lane_id in DEFAULT_WEIGHTS else None
    loop = lane.get("learning_loop") or {}
    scoring_version = loop.get("scoring_version")
    episodes.append(
        {
            "episode_id": "current",
            "kind": "current",
            "from": _utcnow_day(),
            "to": _utcnow_day(),
            "divergence_pct": _divergence_pct(DEFAULT_WEIGHTS.get(lane_id, 1.0), current_w),
            "weight_before": DEFAULT_WEIGHTS.get(lane_id, 1.0),
            "weight_after": current_w,
            "accuracy_in_window": loop.get("accuracy"),
            "graded_n": loop.get("graded_n"),
            "formula_expression": formula.get("expression"),
            "trigger_subnets": [],
            "narrative": (
                current_state_story(
                    label,
                    current_w,
                    int(loop.get("graded_n") or 0),
                    loop.get("accuracy"),
                    scoring_version,
                )
                if current_w is not None and loop.get("graded_n")
                else f"{label} is warming up — not enough graded picks yet."
            ),
        }
    )

    middle = [e for e in episodes if e["kind"] not in ("origin", "current")]
    middle.sort(
        key=lambda e: (
            str(e.get("from") or ""),
            _EPISODE_SORT.get(str(e.get("kind") or ""), 50),
            str(e.get("episode_id") or ""),
        )
    )
    ordered = [episodes[0]] + middle + [episodes[-1]]

    return {
        "lane_id": lane_id,
        "label": label,
        "episode_count": len(ordered),
        "trail": ordered,
        "summary": evolution_trail_summary(len(ordered), label),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _utcnow_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_all_evolution_trails() -> Dict[str, Any]:
    trails = []
    for lane_id in LANE_IDS:
        trail = build_evolution_trail(lane_id)
        if trail:
            trails.append(trail)
    return {"status": "ok", "trails": trails, "updated_at": _utcnow_day()}
