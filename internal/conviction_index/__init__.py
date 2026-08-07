"""
Telegram Conviction Index engine — message-primary weighted consensus.

Formula constants are env-tunable but default to the validated spec values.
Direction is derived from signed momentum only (never UI verdict labels).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

GAMMA = float(os.environ.get("CONVICTION_INDEX_GAMMA", "2.5"))
KAPPA = float(os.environ.get("CONVICTION_INDEX_KAPPA", "1.2"))
ALPHA = float(os.environ.get("CONVICTION_INDEX_ALPHA", "3"))
BETA = float(os.environ.get("CONVICTION_INDEX_BETA", "3"))
HALF_LIFE_HOURS = float(os.environ.get("CONVICTION_INDEX_HALF_LIFE_HOURS", "24"))
_LAMBDA = math.log(2) / HALF_LIFE_HOURS

_INDEX_PATH = os.environ.get("CONVICTION_INDEX_PATH", "data/conviction_index.json")

_BULL = frozenset({"up", "bull", "bullish", "long", "buy", "accumulate", "moon"})
_BEAR = frozenset({"down", "bear", "bearish", "short", "sell", "reduce", "fade", "dump"})

_TIMEFRAME_HOURS = {
    "1h": 1,
    "4h": 4,
    "24h": 24,
    "1d": 24,
    "7d": 168,
    "1w": 168,
}


def author_weight(calls: int = 0, correct: int = 0, *, author_id: Optional[str] = None) -> float:
    """W(a) with unknown-author floor 0.50 (never zero)."""
    calls = max(0, int(calls or 0))
    correct = max(0, min(int(correct or 0), calls))
    conf = calls / (calls + 6) if calls >= 0 else 0.0
    rate = (correct + ALPHA) / (calls + ALPHA + BETA)
    weight = 0.5 + (rate - 0.5) * conf
    return max(0.5, weight)


def decay_factor(age_hours: float) -> float:
    """Recency decay with 24h half-life."""
    age = max(0.0, float(age_hours or 0))
    return math.exp(-_LAMBDA * age)


def signed_strength(conviction: float, direction_sign: int) -> float:
    """Message-primary strength: (conviction/100)^gamma * sign(direction)."""
    conv = max(0.0, min(100.0, float(conviction or 0)))
    sign = 0 if direction_sign == 0 else (1 if direction_sign > 0 else -1)
    if sign == 0:
        return 0.0
    return (conv / 100.0) ** GAMMA * sign


def momentum_sign(predicted_direction: Optional[str], *, momentum: Optional[float] = None) -> int:
    """Direction from signed momentum / predicted_direction only — not verdict UI labels."""
    if momentum is not None:
        m = float(momentum)
        if m > 0:
            return 1
        if m < 0:
            return -1
        return 0
    text = str(predicted_direction or "").strip().lower()
    if text in _BULL:
        return 1
    if text in _BEAR:
        return -1
    return 0


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Weighted median; empty inputs return 0.0."""
    if not values or not weights:
        return 0.0
    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    total = sum(max(0.0, float(w)) for _, w in pairs)
    if total <= 0:
        return float(pairs[len(pairs) // 2][0])
    half = total / 2.0
    cumulative = 0.0
    for val, wt in pairs:
        cumulative += max(0.0, float(wt))
        if cumulative >= half:
            return float(val)
    return float(pairs[-1][0])


def _timeframe_hours(raw: Any) -> float:
    if raw is None:
        return 24.0
    if isinstance(raw, (int, float)):
        return max(1.0, float(raw))
    text = str(raw).strip().lower()
    if text in _TIMEFRAME_HOURS:
        return float(_TIMEFRAME_HOURS[text])
    m = re.search(r"(\d+(?:\.\d+)?)\s*(h|d|w)?", text)
    if not m:
        return 24.0
    val = float(m.group(1))
    unit = m.group(2) or "h"
    if unit == "d":
        return val * 24.0
    if unit == "w":
        return val * 168.0
    return val


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_hours(msg: Dict[str, Any], *, now: Optional[datetime] = None) -> float:
    if "age_hours" in msg and msg["age_hours"] is not None:
        return max(0.0, float(msg["age_hours"]))
    ts = _parse_ts(msg.get("timestamp"))
    if ts is None:
        return 0.0
    ref = now or datetime.now(timezone.utc)
    return max(0.0, (ref - ts).total_seconds() / 3600.0)


def compute_index(
    messages: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute conviction index + confidence for one subnet's message set."""
    if not messages:
        return {
            "index": 50.0,
            "confidence_pct": 0.0,
            "direction": "neutral",
            "direction_sign": 0,
            "timeframe_hours": 0.0,
            "trend_spark": 0.0,
            "flagged": True,
            "new_voice": True,
            "note": "new voice — counts, weight grows as calls resolve",
            "message_count": 0,
            "raw": 0.0,
        }

    ref = now or datetime.now(timezone.utc)
    num = 0.0
    den = 0.0
    signed_sum = 0.0
    tf_values: List[float] = []
    tf_weights: List[float] = []
    recent_w = 0.0
    recent_s = 0.0
    prior_w = 0.0
    prior_s = 0.0
    any_new = False

    for msg in messages:
        conviction = float(msg.get("conviction") or 0)
        direction_sign = msg.get("direction_sign")
        if direction_sign is None:
            direction_sign = momentum_sign(
                msg.get("predicted_direction"),
                momentum=msg.get("momentum"),
            )
        direction_sign = int(direction_sign)
        calls = int(msg.get("calls") or msg.get("total_messages") or 0)
        correct = int(msg.get("correct") or msg.get("correct_predictions") or 0)
        w = author_weight(calls, correct, author_id=msg.get("author_id"))
        age = _age_hours(msg, now=ref)
        decay = decay_factor(age)
        s = signed_strength(conviction, direction_sign)

        contrib = s * w * decay
        weight_mass = w * decay
        num += contrib
        den += weight_mass
        signed_sum += contrib

        tf_h = _timeframe_hours(msg.get("predicted_timeframe") or msg.get("timeframe"))
        tf_values.append(tf_h)
        tf_weights.append(abs(weight_mass) + 1e-9)

        if age <= 6.0:
            recent_w += weight_mass
            recent_s += contrib
        elif age <= 24.0:
            prior_w += weight_mass
            prior_s += contrib

        if calls == 0:
            any_new = True

    raw = num / (den + KAPPA) if (den + KAPPA) > 0 else 0.0
    index = 50.0 + raw * 50.0
    rho = den / (den + KAPPA) if (den + KAPPA) > 0 else 0.0
    confidence_pct = rho * 100.0

    # ponytail: neutral deadband — near-cancelled momentum reads neutral, not bull/bear
    if abs(raw) < 0.03:
        direction_sign = 0
        direction = "neutral"
    elif signed_sum > 0:
        direction_sign = 1
        direction = "bullish"
    elif signed_sum < 0:
        direction_sign = -1
        direction = "bearish"
    else:
        direction_sign = 0
        direction = "neutral"

    tf_hours = weighted_median(tf_values, tf_weights)
    recent_mean = recent_s / recent_w if recent_w > 0 else 0.0
    prior_mean = prior_s / prior_w if prior_w > 0 else 0.0
    trend_spark = recent_mean - prior_mean

    low_confidence = confidence_pct < 35.0 or len(messages) < 2
    flagged = low_confidence or any_new
    note = ""
    if any_new and confidence_pct < 50.0:
        note = "new voice — counts, weight grows as calls resolve"

    return {
        "index": round(index, 1),
        "confidence_pct": round(confidence_pct, 0),
        "direction": direction,
        "direction_sign": direction_sign,
        "timeframe_hours": round(tf_hours, 1),
        "trend_spark": round(trend_spark, 4),
        "flagged": flagged,
        "new_voice": any_new,
        "note": note,
        "message_count": len(messages),
        "raw": raw,
    }


def _load_index_state() -> Dict[str, Any]:
    if not os.path.exists(_INDEX_PATH):
        return {"subnets": {}, "leaderboard": {}, "updated_at": None}
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("conviction index state read failed: %s", exc)
        return {"subnets": {}, "leaderboard": {}, "updated_at": None}


def _save_index_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_INDEX_PATH) or ".", exist_ok=True)
    tmp = _INDEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, _INDEX_PATH)


def _rows_for_subnet(messages: List[Dict[str, Any]], netuid: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in messages:
        nu = row.get("netuid")
        if nu is None:
            continue
        if int(nu) == int(netuid):
            out.append(row)
    return out


def _normalize_message_row(row: Dict[str, Any], *, now: datetime) -> Dict[str, Any]:
    rel = row.get("author_reliability") or {}
    calls = int(rel.get("total_messages") or row.get("total_messages") or 0)
    correct = int(rel.get("correct_predictions") or row.get("correct_predictions") or 0)
    return {
        "message_id": row.get("message_id") or row.get("id"),
        "netuid": row.get("netuid"),
        "author_id": row.get("author_id"),
        "author_name": row.get("author_name"),
        "conviction": float(row.get("conviction") or 0),
        "predicted_direction": row.get("predicted_direction"),
        "predicted_timeframe": row.get("predicted_timeframe"),
        "timestamp": row.get("timestamp"),
        "calls": calls,
        "correct": correct,
        "age_hours": _age_hours(row, now=now),
    }


def populate_author_reliability(*, lookback_days: int = 90) -> Dict[str, Any]:
    """Best-effort join of message_intel SQLite into conviction index state."""
    try:
        from internal.message_intel.store import get_db
    except Exception as exc:
        logger.debug("populate_author_reliability skipped: %s", exc)
        return {"ok": False, "error": str(exc)}

    now = datetime.now(timezone.utc)
    db = get_db()
    try:
        with db._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id AS message_id, m.author_id, m.author_name, m.timestamp,
                       v.conviction, v.predicted_direction, v.predicted_timeframe,
                       ps.netuid,
                       ar.total_messages, ar.correct_predictions, ar.accuracy_score,
                       po.outcome
                FROM messages m
                JOIN message_verdicts v ON v.message_id = m.id
                LEFT JOIN price_snapshots ps ON ps.message_id = m.id
                LEFT JOIN author_reliability ar ON ar.author_id = m.author_id
                LEFT JOIN price_outcomes po ON po.message_id = m.id
                WHERE ps.netuid IS NOT NULL
                ORDER BY m.id DESC
                LIMIT 5000
                """
            ).fetchall()
    except Exception as exc:
        logger.warning("conviction index populate query failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    by_subnet: Dict[int, List[Dict[str, Any]]] = {}
    authors: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        d = dict(row)
        netuid = d.get("netuid")
        if netuid is None:
            continue
        nu = int(netuid)
        norm = _normalize_message_row(d, now=now)
        by_subnet.setdefault(nu, []).append(norm)

        aid = str(d.get("author_id") or "")
        if not aid:
            continue
        bucket = authors.setdefault(
            aid,
            {
                "author_id": aid,
                "author_name": d.get("author_name"),
                "long_hits": 0,
                "long_total": 0,
                "fade_hits": 0,
                "fade_total": 0,
                "contra_fade_hits": 0,
                "contra_fade_total": 0,
            },
        )
        sign = momentum_sign(d.get("predicted_direction"))
        outcome = str(d.get("outcome") or "").lower()
        hit = outcome == "hit"
        if sign > 0:
            bucket["long_total"] += 1
            bucket["long_hits"] += int(hit)
        elif sign < 0:
            bucket["fade_total"] += 1
            bucket["fade_hits"] += int(hit)

    subnet_scores: Dict[str, Any] = {}
    for netuid, msgs in by_subnet.items():
        subnet_scores[str(netuid)] = compute_index(msgs, now=now)

    ranked = sorted(
        ((int(k), v) for k, v in subnet_scores.items()),
        key=lambda item: item[1].get("index", 50.0),
        reverse=True,
    )
    top5 = [
        {"netuid": nu, **score}
        for nu, score in ranked[:5]
    ]

    state = {
        "subnets": subnet_scores,
        "top5": top5,
        "leaderboard": authors,
        "updated_at": now.isoformat(),
    }
    _save_index_state(state)
    return {"ok": True, "subnet_count": len(subnet_scores), "author_count": len(authors)}


def get_conviction_snapshot(*, refresh: bool = False) -> Dict[str, Any]:
    """Return persisted snapshot; optionally refresh from SQLite first."""
    if refresh:
        populate_author_reliability()
    state = _load_index_state()
    if not state.get("subnets"):
        populate_author_reliability()
        state = _load_index_state()
    return state


def build_leaderboard(*, days: int = 30) -> Dict[str, Any]:
    """Leaderboard with separate long vs fade accuracy; low-confidence rows visible."""
    state = get_conviction_snapshot()
    authors = state.get("leaderboard") or {}
    rows: List[Dict[str, Any]] = []
    for aid, bucket in authors.items():
        long_total = int(bucket.get("long_total") or 0)
        fade_total = int(bucket.get("fade_total") or 0)
        long_hits = int(bucket.get("long_hits") or 0)
        fade_hits = int(bucket.get("fade_hits") or 0)
        long_acc = (long_hits / long_total * 100.0) if long_total else None
        fade_acc = (fade_hits / fade_total * 100.0) if fade_total else None
        total_calls = long_total + fade_total
        new_voice = total_calls < 3
        row = {
            "author_id": aid,
            "author_name": bucket.get("author_name"),
            "long_accuracy_pct": round(long_acc, 1) if long_acc is not None else None,
            "fade_accuracy_pct": round(fade_acc, 1) if fade_acc is not None else None,
            "long_total": long_total,
            "fade_total": fade_total,
            "total_calls": total_calls,
            "new_voice": new_voice,
            "low_confidence": new_voice,
            "note": (
                "new voice — counts, weight grows as calls resolve"
                if new_voice
                else ""
            ),
        }
        rows.append(row)
    rows.sort(key=lambda r: (r["total_calls"], r.get("long_accuracy_pct") or 0), reverse=True)
    return {
        "days": days,
        "count": len(rows),
        "authors": rows[:50],
    }


def health_payload() -> Dict[str, Any]:
    state = _load_index_state()
    return {
        "status": "ok",
        "module": "conviction_index",
        "gamma": GAMMA,
        "kappa": KAPPA,
        "half_life_hours": HALF_LIFE_HOURS,
        "subnet_count": len(state.get("subnets") or {}),
        "updated_at": state.get("updated_at"),
    }
