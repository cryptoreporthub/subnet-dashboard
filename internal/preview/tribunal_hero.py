"""SSR fixtures for /preview/tribunal — Council Hero v4."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request

_VALID_STATES = frozenset({"sealed", "gated", "forming", "cold"})
_JUDGE_KEYS = ("oracle", "echo", "pulse")


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


def conviction_pct(payload: Dict[str, Any]) -> Optional[float]:
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
    return val


def _judge_score_pct(raw: Any) -> Optional[float]:
    if isinstance(raw, dict):
        for key in ("confidence", "score"):
            if raw.get(key) is not None:
                try:
                    val = float(raw[key])
                    return val * 100 if val <= 1 else val
                except (TypeError, ValueError):
                    continue
    elif raw is not None:
        try:
            val = float(raw)
            return val * 100 if val <= 1 else val
        except (TypeError, ValueError):
            pass
    return None


def judge_signals_from_pick(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    active = payload.get("pick") or payload.get("candidate") or {}
    scores = active.get("judge_scores_at_creation")
    if not isinstance(scores, dict):
        netuid = None
        sn = active.get("subnet") if isinstance(active.get("subnet"), dict) else {}
        if isinstance(sn, dict):
            netuid = sn.get("netuid")
        if netuid is not None:
            try:
                from internal.council.conviction_bands import judge_scores_for_netuid

                scores = judge_scores_for_netuid(netuid)
            except Exception:
                scores = None
    out: Dict[str, Optional[float]] = {k: None for k in _JUDGE_KEYS}
    if isinstance(scores, dict):
        for key in _JUDGE_KEYS:
            out[key] = _judge_score_pct(scores.get(key))
    return out


def weighted_verdict_pct(
    weights: Dict[str, float],
    signals: Dict[str, Optional[float]],
) -> Optional[float]:
    """Σ(weight_j × signal_j_pct) — e.g. 0.4×36 + 0.3×32 + 0.3×32 = 33.6."""
    total = 0.0
    used = False
    for key in _JUDGE_KEYS:
        w = weights.get(key)
        s = signals.get(key)
        if w is None or s is None:
            continue
        total += float(w) * float(s)
        used = True
    if not used:
        return None
    return round(total, 1)


def format_gauge_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    if abs(val - round(val)) < 0.05:
        return f"{int(round(val))}%"
    return f"{val:.1f}%"


def gauge_attr(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    if abs(val - round(val)) < 0.05:
        return str(int(round(val)))
    return f"{val:.1f}"


def gauge_pct_for_view(
    payload: Dict[str, Any],
    weights: Dict[str, float],
) -> Optional[float]:
    signals = judge_signals_from_pick(payload)
    weighted = weighted_verdict_pct(weights, signals)
    if weighted is not None:
        return weighted
    raw = conviction_pct(payload)
    if raw is None:
        return None
    return round(raw, 1)


def synced_at_iso(payload: Dict[str, Any]) -> Optional[str]:
    pick = payload if isinstance(payload, dict) else {}
    meta = pick.get("_meta") or {}
    for source in (pick, meta):
        for key in ("timestamp_utc", "generated_at"):
            val = source.get(key)
            if val:
                return str(val)
    return None


def subnet_label(payload: Dict[str, Any]) -> str:
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


_EQUAL_WEIGHT_SPREAD = 0.015  # normalized fractions (~1.5pp)


def _format_judge_weight_pct(weights: Dict[str, float], key: str) -> str:
    """Trust-weight share for verdict blend — not the judge's signal score."""
    if weights.get(key) is None:
        return "—"
    try:
        vals = [float(weights[k]) for k in _JUDGE_KEYS if weights.get(k) is not None]
        w = float(weights[key])
    except (TypeError, ValueError):
        return "—"
    if len(vals) >= 2 and max(vals) - min(vals) < _EQUAL_WEIGHT_SPREAD:
        return "Equal weight"
    pct = w * 100.0
    if abs(pct - round(pct)) < 0.05:
        return f"{int(round(pct))}%"
    return f"{pct:.1f}%"


def _judge_agreement_labels(signals: Dict[str, Optional[float]]) -> Dict[str, str]:
    """Consensus/dissent from the three judge signal scores already on the pick."""
    vals: List[float] = []
    for key in _JUDGE_KEYS:
        raw = signals.get(key)
        if raw is None:
            continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if len(vals) < 2:
        return {"consensus": "—", "dissent": "—"}

    spread = max(vals) - min(vals)
    if spread <= 10:
        consensus = "High agreement"
    elif spread <= 25:
        consensus = "Moderate agreement"
    else:
        consensus = "Low agreement"

    if spread < 1:
        dissent = "Unanimous"
    elif spread >= 30:
        dissent = f"High dissent · {spread:.0f} pts"
    else:
        dissent = f"{spread:.0f} pt spread"

    return {"consensus": consensus, "dissent": dissent}


def _format_signal_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    if abs(val - round(val)) < 0.05:
        return f"{int(round(val))}%"
    return f"{val:.1f}%"


def _delta_arrow(delta: Optional[float]) -> str:
    if delta is None:
        return "·"
    if delta > 0.0005:
        return "▲"
    if delta < -0.0005:
        return "▼"
    return "·"


def _decision_log_panel(
    payload: Dict[str, Any],
    kind: str,
    gauge: Optional[float],
    signals: Optional[Dict[str, Optional[float]]] = None,
) -> Dict[str, Any]:
    active = payload.get("pick") or payload.get("candidate") or {}
    agreement = _judge_agreement_labels(signals or {})

    consensus_str = agreement["consensus"]
    if consensus_str == "—":
        consensus = active.get("consensus_score")
        if consensus is not None:
            try:
                cval = float(consensus)
                consensus_str = f"{cval * 100:.0f}%" if cval <= 1 else f"{cval:.0f}%"
            except (TypeError, ValueError):
                consensus_str = "—"

    brain = (
        active.get("brain_recommendation")
        or active.get("recommended_action")
        or payload.get("brain_recommendation")
    )
    if isinstance(brain, dict):
        brain = brain.get("action") or brain.get("recommended_action")
    brain_str = str(brain).upper() if brain else "—"

    dissent_str = agreement["dissent"]
    if dissent_str == "—":
        dissenters = payload.get("dissenters")
        if not isinstance(dissenters, list):
            dissenters = active.get("dissenters")
        if isinstance(dissenters, list) and dissenters:
            dissent_str = ", ".join(str(d) for d in dissenters)
        else:
            dissent_str = "Unanimous" if payload.get("council_unanimous") else "—"

    return {
        "verdict_kind": kind.upper(),
        "confidence": format_gauge_pct(gauge),
        "consensus": consensus_str,
        "brain": brain_str,
        "dissent": dissent_str,
    }


def _accuracy_ledger_panel(stats: Dict[str, Any]) -> Dict[str, Any]:
    tb = stats.get("trust_banner") or {}
    graded = int(tb.get("graded") or 0)
    correct = int(tb.get("correct") or 0)
    wrong = int(tb.get("wrong") or 0)
    win_rate = None
    if tb.get("ready") and tb.get("accuracy") is not None:
        win_rate = round(float(tb["accuracy"]) * 100, 1)
    elif graded > 0 and correct + wrong > 0:
        win_rate = round(correct / (correct + wrong) * 100, 1)
    return {
        "graded": graded,
        "correct": correct,
        "wrong": wrong,
        "win_rate": f"{win_rate:.1f}%" if win_rate is not None else "—",
        "sub": tb.get("headline") or tb.get("message") or "Building sample",
        "ready": bool(tb.get("ready")),
    }


def _jury_move_panel(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    deltas = stats.get("judge_weight_deltas") or {}
    rows: List[Dict[str, Any]] = []
    for key, label in (("oracle", "ORACLE"), ("echo", "ECHO"), ("pulse", "PULSE")):
        delta = deltas.get(key) if isinstance(deltas, dict) else None
        try:
            delta_f = float(delta) if delta is not None else None
        except (TypeError, ValueError):
            delta_f = None
        rows.append(
            {
                "key": key,
                "label": label,
                "arrow": _delta_arrow(delta_f),
                "delta": f"{delta_f:+.3f}" if delta_f is not None else "—",
            }
        )
    return rows


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
                "judge_scores_at_creation": {
                    "oracle": {"confidence": 0.72},
                    "echo": {"confidence": 0.70},
                    "pulse": {"confidence": 0.71},
                },
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
                "judge_scores_at_creation": {
                    "oracle": {"confidence": 0.36},
                    "echo": {"confidence": 0.32},
                    "pulse": {"confidence": 0.32},
                },
            },
        }
    if state == "forming":
        return {"status": "pending", "date": today, "action": "HOLD", "pick": None, "candidate": None}
    return {"status": "timeout", "date": today, "action": "HOLD", "pick": None, "candidate": None}


def _fixture_learning_stats(state: str) -> Dict[str, Any]:
    weights = {"oracle": 0.40, "echo": 0.30, "pulse": 0.30}
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
            "judge_weight_deltas": {"oracle": 0.02, "echo": -0.01, "pulse": 0.0},
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
            "judge_weight_deltas": {"pulse": -0.02},
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


def build_tribunal_view(
    daily_pick: Dict[str, Any],
    learning_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Build tribunal hero template context from live or fixture data."""
    pick = daily_pick if isinstance(daily_pick, dict) else {}
    stats = learning_stats if isinstance(learning_stats, dict) else {}
    kind = verdict_kind(pick)
    weights = stats.get("judge_weights") or {}
    signals = judge_signals_from_pick(pick)
    gauge = gauge_pct_for_view(pick, weights) if kind not in ("forming", "cold") else None
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
                "weight_pct": _format_judge_weight_pct(weights, key),
                "signal_pct": _format_signal_pct(signals.get(key)),
                "last5": last5 if isinstance(last5, list) and len(last5) == 5 else None,
            }
        )

    headline = center_label(pick, kind)
    if gauge is not None:
        headline = f"{headline} — {format_gauge_pct(gauge)} conviction"

    return {
        "verdict_kind": kind,
        "subnet_label": subnet_label(pick),
        "center_label": center_label(pick, kind),
        "conviction_pct": gauge,
        "gauge_display": format_gauge_pct(gauge),
        "gauge_attr": gauge_attr(gauge),
        "synced_at": synced_at_iso(pick),
        "judges": judges,
        "panels": {
            "decision_log": _decision_log_panel(pick, kind, gauge, signals),
            "accuracy_ledger": _accuracy_ledger_panel(stats),
            "jury_move": _jury_move_panel(stats),
        },
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
