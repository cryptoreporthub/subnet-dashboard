"""SSR fixtures for /preview/tribunal — tribunal hero visual sign-off."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request

_VALID_STATES = frozenset({"sealed", "gated", "forming", "cold"})
_RING_CIRC = 452.39  # 2πr, r=72 — keep in sync with tribunal_hero.html SVG


def verdict_kind(payload: Dict[str, Any]) -> str:
    act = str(payload.get("action") or "HOLD").upper()
    if act == "BUY":
        act = "LONG"
    if payload.get("pick") and act == "LONG":
        return "sealed"
    if not payload.get("pick") and payload.get("candidate") and act == "HOLD":
        return "gated"
    if str(payload.get("status") or "").lower() == "pending":
        return "forming"
    return "cold"


def center_label(payload: Dict[str, Any], kind: str) -> str:
    if kind == "sealed":
        act = str(payload.get("action") or "LONG").upper()
        if act == "BUY":
            act = "LONG"
        return f"SEALED · {act}"
    if kind == "gated":
        return "GATED · HOLD"
    if kind == "forming":
        return "FORMING"
    return "COLD"


def conviction_pct(payload: Dict[str, Any]) -> Optional[int]:
    active = payload.get("pick") or payload.get("candidate")
    if not active:
        return None
    raw = (
        active.get("final_confidence")
        if active.get("final_confidence") is not None
        else active.get("confidence")
        if active.get("confidence") is not None
        else active.get("conviction")
    )
    if raw is None:
        return None
    val = float(raw)
    if val <= 1:
        val *= 100
    return int(round(val))


def ring_dash_offset(pct: Optional[int]) -> float:
    if pct is None:
        return _RING_CIRC
    clamped = max(0, min(100, int(pct)))
    return _RING_CIRC - (_RING_CIRC * clamped / 100)


def synced_at_iso(payload: Dict[str, Any]) -> Optional[str]:
    """ISO timestamp for hero sync stamp — matches dailyPickGeneratedAt() in cockpit_hydrate.js."""
    pick = payload if isinstance(payload, dict) else {}
    meta = pick.get("_meta") or {}
    for source in (pick, meta):
        for key in ("timestamp_utc", "generated_at"):
            val = source.get(key)
            if val:
                return str(val)
    return None


def subnet_label(payload: Dict[str, Any]) -> str:
    """Visible hero title: SN{netuid} · name when name is distinct."""
    active = payload.get("pick") or payload.get("candidate")
    if not active:
        return "Awaiting subnet"
    subnet = active.get("subnet") if isinstance(active.get("subnet"), dict) else {}
    name = str(subnet.get("name") or "").strip()
    netuid = subnet.get("netuid")
    if netuid is None:
        return name or "—"
    sn_prefix = f"SN{netuid}"
    if not name or name.upper() == sn_prefix.upper() or re.match(r"^SN\d+$", name, re.I):
        return sn_prefix
    return f"{sn_prefix} · {name}"


def _judge_weight_pct(weight: float) -> str:
    return f"{int(round(float(weight) * 100))}%"


def _fixture_daily_pick(state: str) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    if state == "sealed":
        return {
            "status": "ok",
            "date": today,
            "action": "LONG",
            "pick": {
                "subnet": {"netuid": 14, "name": "TaoHash", "symbol": "TH"},
                "final_confidence": 0.71,
                "action": "LONG",
            },
            "candidate": None,
        }
    if state == "gated":
        return {
            "status": "ok",
            "date": today,
            "action": "HOLD",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": 99, "name": "SN99", "symbol": "T99"},
                "final_confidence": 0.34,
                "action": "LONG",
            },
        }
    if state == "forming":
        return {"status": "pending", "date": today, "action": "HOLD", "pick": None, "candidate": None}
    return {"status": "timeout", "date": today, "action": "HOLD", "pick": None, "candidate": None}


def _fixture_learning_stats(state: str) -> Dict[str, Any]:
    weights = {"oracle": 0.333, "echo": 0.333, "pulse": 0.334}
    if state == "sealed":
        trust = {
            "ready": True,
            "graded": 443,
            "correct": 139,
            "wrong": 304,
            "accuracy": 0.314,
            "headline": "Last 443 graded: 31% directionally right",
            "message": None,
        }
        return {
            "judge_weights": weights,
            "judge_last5": {
                "oracle": [True, True, None, True, False],
                "echo": [True, False, True, True, False],
                "pulse": [None, True, True, True, True],
            },
            "council_last5": [True, True, True, False, False],
            "trust_banner": trust,
        }
    if state == "gated":
        return {
            "judge_weights": weights,
            "trust_banner": {
                "ready": False,
                "graded": 12,
                "correct": 4,
                "wrong": 8,
                "accuracy": None,
                "headline": None,
                "message": "Not enough graded picks yet (12/30)",
            },
        }
    return {
        "judge_weights": weights,
        "trust_banner": {
            "ready": False,
            "graded": 0,
            "correct": 0,
            "wrong": 0,
            "accuracy": None,
            "headline": None,
            "message": "Not enough graded picks yet (0/30)",
        },
    }


def _metrics_rows(stats: Dict[str, Any]) -> Dict[str, Any]:
    tb = stats.get("trust_banner") or {}
    accuracy_row: Dict[str, Any]
    if tb.get("ready") and tb.get("accuracy") is not None:
        acc_pct = int(round(float(tb["accuracy"]) * 100))
        accuracy_row = {
            "label": "Historical Accuracy",
            "value": f"{acc_pct}%",
            "sub": tb.get("headline") or "",
            "bar_pct": acc_pct,
        }
    else:
        accuracy_row = {
            "label": "Historical Accuracy",
            "value": "—",
            "sub": tb.get("message") or "Sample building",
            "bar_pct": None,
        }

    graded = int(tb.get("graded") or 0)
    correct = int(tb.get("correct") or 0)
    wrong = int(tb.get("wrong") or 0)
    recent_row: Dict[str, Any] = {
        "label": "Recent Verdicts",
        "value": "—",
        "sub": "",
        "ticks": [],
        "bar_pct": None,
    }
    if graded > 0:
        win = int(round(correct / (correct + wrong) * 100)) if (correct + wrong) > 0 else 0
        recent_row["value"] = f"{win}%"
        recent_row["sub"] = f"Last {graded} graded council calls"
        recent_row["bar_pct"] = win
    council_last5 = stats.get("council_last5")
    if isinstance(council_last5, list) and len(council_last5) == 5:
        recent_row["ticks"] = council_last5

    return {"accuracy": accuracy_row, "recent": recent_row}


def build_tribunal_view(
    daily_pick: Dict[str, Any],
    learning_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Build tribunal hero template context from live or fixture data."""
    pick = daily_pick if isinstance(daily_pick, dict) else {}
    stats = learning_stats if isinstance(learning_stats, dict) else {}
    kind = verdict_kind(pick)
    pct = conviction_pct(pick)
    weights = stats.get("judge_weights") or {}
    judge_last5 = stats.get("judge_last5")
    judges: List[Dict[str, Any]] = []
    for key, label in (("oracle", "ORACLE"), ("echo", "ECHO"), ("pulse", "PULSE")):
        w = weights.get(key)
        last5 = None
        if isinstance(judge_last5, dict):
            last5 = judge_last5.get(key)
        judges.append(
            {
                "key": key,
                "label": label,
                "weight_pct": _judge_weight_pct(w) if w is not None else "—",
                "last5": last5 if isinstance(last5, list) and len(last5) == 5 else None,
            }
        )

    metrics = _metrics_rows(stats)
    headline = center_label(pick, kind)
    if pct is not None:
        headline = f"{headline} — {pct}% conviction"

    return {
        "verdict_kind": kind,
        "subnet_label": subnet_label(pick),
        "center_label": center_label(pick, kind),
        "conviction_pct": pct,
        "synced_at": synced_at_iso(pick),
        "ring_circ": _RING_CIRC,
        "ring_dash_offset": ring_dash_offset(pct),
        "judges": judges,
        "metrics": metrics,
        "headline": headline,
        "daily_pick": pick,
        "learning_stats": stats,
    }


def build_tribunal_hero_preview_context(request: Request) -> Dict[str, Any]:
    """Full SSR context for /preview/tribunal."""
    state = str(request.query_params.get("state") or "gated").lower()
    if state not in _VALID_STATES:
        state = "gated"

    daily_pick = _fixture_daily_pick(state)
    learning_stats = _fixture_learning_stats(state)

    return {
        "request": request,
        "public_base_url": str(request.base_url).rstrip("/"),
        "preview_mode": True,
        "preview_state": state,
        "tribunal": build_tribunal_view(daily_pick, learning_stats),
    }
