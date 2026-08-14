"""
Telegram Proof Contract — single canonical eligibility + outcome classifier.

Every leaderboard, proof band, receipt card, and inline feed outcome MUST use
these helpers so the numbers can never disagree. Grading is based on resolved
price prices only and NEVER on reaction counts, views, forwards, or ungraded
chatter.

Eligibility (a "qualified call")
  - source == 'telegram'
  - a non-empty, normalised direction (up / down / flat)
  - conviction >= MIN_CONVICTION (jury score, default 60)
  - a positive finite price snapshot (baseline > 0)
  - a recorded resolved outcome (price_outcomes.outcome is not null)

Grading (canonical, aligned with self_learning._is_correct_prediction)
  hit      — direction confirms:
               up + {pump, mild_pump} (or pump_pct_max > 2.0)
               down + {dump, mild_dump}
               flat + stable
  miss     — direction refuted:
               up + {dump, mild_dump}
               down + {pump, mild_pump}
               flat + any movement
  neutral  — resolved but neither confirmed nor refuted:
               up/down + stable (flat market). Shown but excluded from accuracy.

Accuracy is hit/(hit+miss): neutral moves and all engagement data are excluded.
Not financial advice.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

# ── Constants (one source of truth) ────────────────────────────────────────

MIN_CONVICTION: float = 60.0          # jury conviction threshold (0–100)
MIN_LEADERBOARD_SAMPLE: int = 5       # resolved calls needed for a firm rank
RESOLVE_HORIZON: str = "24h"          # documented proof window

OC_HIT = "hit"
OC_MISS = "miss"
OC_NEUTRAL = "neutral"
OC_PENDING = "pending"
OC_UNQUALIFIED = "unqualified"

EV_RESOLVED = "resolved"
EV_PENDING = "pending"
EV_UNQUALIFIED = "unqualified"

_UP_DIRS = frozenset(("up", "bullish", "long", "buy"))
_DOWN_DIRS = frozenset(("down", "bearish", "short", "sell"))
_FLAT_DIRS = frozenset(("flat", "sideways", "neutral", "hold"))
_PUMP_OUTCOMES = frozenset(("pump", "mild_pump"))
_DUMP_OUTCOMES = frozenset(("dump", "mild_dump"))
_STABLE_OUTCOME = "stable"


def resolve_direction(verdict: Optional[str], predicted_direction: Optional[str]) -> Optional[str]:
    """
    Resolve the prediction direction exactly as the locked correct-prediction
    rule in message_intel/self_learning.py._is_correct_prediction selects its
    branch: a bull verdict OR up direction counts as up; a bear verdict OR down
    direction counts as down; anything else with a stored signal is a flat
    call. Returns None when NO prediction signal exists at all (chatter).
    """
    v = str(verdict or "").strip().lower()
    d = str(predicted_direction or "").strip().lower()
    if v == "bullish" or d == "up":
        return "up"
    if v == "bearish" or d == "down":
        return "down"
    if v in _FLAT_DIRS or v in _UP_DIRS or v in _DOWN_DIRS or d in _FLAT_DIRS or d in _UP_DIRS or d in _DOWN_DIRS:
        return "flat"
    return None


def is_correct(direction: Optional[str], outcome: str, pump_pct: Optional[float]) -> bool:
    """
    Boolean correctness mirroring self_learning._is_correct_prediction for the
    resolved direction. Exposed so tests can prove classifier parity.
    """
    outcome = str(outcome or "").lower()
    if direction == "up":
        return outcome in _PUMP_OUTCOMES or (pump_pct is not None and pump_pct > 2.0)
    if direction == "down":
        return outcome in _DUMP_OUTCOMES
    return outcome == _STABLE_OUTCOME


def stable_author_id(row: Dict[str, Any]) -> str:
    """
    Stable identity key for a Telegram caller.

    Priority: author_id → author_username → author_name. A real author_id is
    never merged with another caller by display name. The prefixed string is
    opaque to clients but deterministic for the same author.
    """
    aid = (row.get("author_id") or "").strip()
    if aid and aid.lower() not in ("", "unknown", "none"):
        return f"id:{aid}"
    uname = (row.get("author_username") or "").strip().lstrip("@")
    if uname and uname.lower() not in ("", "unknown", "none"):
        return f"u:{uname.lower()}"
    name = (row.get("author_name") or "").strip()
    return f"n:{name}" if name else "unknown"


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _about_tao(row: Dict[str, Any]) -> bool:
    """Allow TAO/USD grading only for explicit TAO messages.

    Rows without message text are legacy/unit records and retain the old TAO
    fallback; real Telegram rows must mention TAO in text or extracted entities.
    """
    if row.get("netuid") is not None:
        return False
    if row.get("about_tao") is True:
        return True
    raw_entities = row.get("entities_json")
    try:
        entities = json.loads(raw_entities) if isinstance(raw_entities, str) else raw_entities
        protocols = entities.get("protocols") if isinstance(entities, dict) else []
        if any(str(item).lower() in {"tao", "dtao"} for item in protocols or []):
            return True
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    content = str(row.get("content") or "")
    if not content:
        return row.get("tao_usd_price") is not None
    return bool(re.search(r"\b(?:d?TAO)\b", content, re.IGNORECASE))


def _classify_status(direction: Optional[str], outcome: str, pump_pct: Optional[float]) -> str:
    """Return OC_HIT | OC_MISS | OC_NEUTRAL for a resolved call."""
    outcome = str(outcome or "").lower()
    if direction == "up":
        if outcome in _PUMP_OUTCOMES or (pump_pct is not None and pump_pct > 2.0):
            return OC_HIT
        if outcome in _DUMP_OUTCOMES:
            return OC_MISS
        return OC_NEUTRAL
    if direction == "down":
        if outcome in _DUMP_OUTCOMES:
            return OC_HIT
        if outcome in _PUMP_OUTCOMES:
            return OC_MISS
        return OC_NEUTRAL
    if direction == "flat":
        if outcome == _STABLE_OUTCOME:
            return OC_HIT
        if outcome in _PUMP_OUTCOMES | _DUMP_OUTCOMES:
            return OC_MISS
        return OC_NEUTRAL
    # No recognised direction — not a prediction.
    return OC_UNQUALIFIED


def classify_call(row: Dict[str, Any], min_conviction: float = MIN_CONVICTION) -> Dict[str, Any]:
    """
    Compute eligibility, resolution, and grade for one message row.

    Expected row keys: source, author_id, author_username, author_name,
    predicted_direction (or verdict), conviction, tao_usd_price (baseline),
    netuid, outcome, pump_pct_max, price_24h.

    Returns a dict with: eligible, status, evaluation, resolved, direction,
    move_pct, raw_outcome, threshold.
    """
    source = str(row.get("source") or "").lower()
    direction = resolve_direction(
        row.get("verdict"), row.get("predicted_direction")
    )
    conviction = _to_float(row.get("conviction")) or 0.0
    baseline = _to_float(row.get("tao_usd_price"))
    outcome = (row.get("outcome") or "").strip()
    pump_pct = _to_float(row.get("pump_pct_max"))
    netuid = row.get("netuid")
    subnet_name = str(row.get("subnet_name") or (f"SN{netuid}" if netuid is not None else "")).strip()
    has_subnet_identity = netuid is not None or bool(subnet_name)
    price_basis = "subnet" if has_subnet_identity else ("tao" if _about_tao(row) else None)

    eligible = (
        source == "telegram"
        and direction is not None
        and conviction >= min_conviction
        and baseline is not None
        and baseline > 0
        and price_basis is not None
    )

    move_pct: Optional[float] = None
    p24 = _to_float(row.get("price_24h"))
    if p24 is not None and baseline and baseline > 0:
        move_pct = round((p24 - baseline) / baseline * 100.0, 2)

    if not eligible:
        return {
            "eligible": False,
            "status": OC_UNQUALIFIED,
            "evaluation": EV_UNQUALIFIED,
            "resolved": False,
            "direction": direction,
            "move_pct": move_pct,
            "price_basis": price_basis,
            "subnet_name": subnet_name or None,
            "raw_outcome": outcome or None,
            "threshold": min_conviction,
        }

    if not outcome:
        return {
            "eligible": True,
            "status": OC_PENDING,
            "evaluation": EV_PENDING,
            "resolved": False,
            "direction": direction,
            "move_pct": move_pct,
            "price_basis": price_basis,
            "subnet_name": subnet_name or None,
            "raw_outcome": None,
            "threshold": min_conviction,
        }

    status = _classify_status(direction, outcome, pump_pct)
    return {
        "eligible": True,
        "status": status,
        "evaluation": EV_RESOLVED,
        "resolved": True,
        "direction": direction,
        "move_pct": move_pct,
        "price_basis": price_basis,
        "subnet_name": subnet_name or None,
        "raw_outcome": outcome,
        "threshold": min_conviction,
    }
