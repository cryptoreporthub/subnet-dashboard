"""Tribunal block for daily_pick — four benches + spectrum from expert_contributions.

Derives a sealed-case view from data the engine already has. No new scoring model.
Fails soft: missing experts → verdict_kind=forming with empty benches.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BENCH_DEFS: Tuple[Tuple[str, str, str], ...] = (
    ("quant", "Quant", "q"),
    ("hype", "Hype", "h"),
    ("dark_horse", "Dark Horse", "d"),
    ("technical", "Technical", "t"),
)

# Stance cutoffs on 0–1 expert contribution (bullishness).
_BUY_FLOOR = 0.58
_SELL_CEIL = 0.42


def _empty_tribunal(*, kind: str = "forming", reason: str = "") -> Dict[str, Any]:
    return {
        "case_id": None,
        "verdict": "HOLD",
        "verdict_kind": kind,  # sealed | gated | forming | cold
        "conviction_pct": 0,
        "concur": {"n": 0, "of": 4},
        "spread": {"pts": 0, "outlier_bench": None, "note": ""},
        "benches": [],
        "gate": {"passed": False, "reason": reason or "", "flip_condition": reason or ""},
        "subnet": None,
        "sealed_at": None,
        "resolves_in": None,
        "horizon": "24h",
        "session_label": "Council warming up",
    }


def _as_pct(value: Any) -> int:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0
    if n <= 1.0:
        n *= 100.0
    return max(0, min(100, int(round(n))))


def _clamp_pos(pos: float) -> float:
    return max(-100.0, min(100.0, pos))


def _stance_from_score(score: float) -> Tuple[str, int, float]:
    """Map 0–1 bullish contribution → stance, confidence %, spectrum position."""
    score = max(0.0, min(1.0, float(score)))
    position = _clamp_pos((score - 0.5) * 200.0)
    if score >= _BUY_FLOOR:
        return "BUY", int(round(score * 100)), position
    if score <= _SELL_CEIL:
        return "SELL", int(round((1.0 - score) * 100)), position
    # HOLD: confidence rises as we leave the exact center
    conf = int(round(50 + abs(score - 0.5) * 100))
    return "HOLD", max(50, min(99, conf)), position


def _extract_experts(block: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not isinstance(block, dict):
        return {}
    raw = block.get("expert_contributions") or block.get("n") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for key, _label, _chip in BENCH_DEFS:
        val = raw.get(key)
        if isinstance(val, (int, float)):
            out[key] = float(val)
    return out


def _active_block(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Prefer published pick; fall back to candidate (gated HOLD path)."""
    pick = payload.get("pick")
    if isinstance(pick, dict) and (pick.get("subnet") or pick.get("netuid")):
        return pick, "pick"
    cand = payload.get("candidate")
    if isinstance(cand, dict) and (cand.get("subnet") or cand.get("netuid")):
        return cand, "candidate"
    return None, ""


def _subnet_from_block(block: Dict[str, Any]) -> Dict[str, Any]:
    sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
    if not isinstance(sn, dict):
        return {}
    netuid = sn.get("netuid")
    try:
        netuid_i = int(netuid) if netuid is not None else None
    except (TypeError, ValueError):
        netuid_i = None
    name = sn.get("name") or sn.get("symbol") or (f"SN{netuid_i}" if netuid_i is not None else "—")
    return {
        "netuid": netuid_i,
        "name": name,
        "symbol": sn.get("symbol") or (f"SN{netuid_i}" if netuid_i is not None else None),
        "description": sn.get("description") or sn.get("category") or "",
    }


def _verdict_from_action(action: Any) -> str:
    a = str(action or "HOLD").upper()
    if a in ("LONG", "BUY"):
        return "BUY"
    if a in ("SHORT", "SELL"):
        return "SELL"
    return "HOLD"


def _case_id(subnet: Dict[str, Any], date_str: Optional[str]) -> Optional[str]:
    netuid = subnet.get("netuid")
    if netuid is None:
        return None
    stamp = ""
    if date_str:
        # YYYY-MM-DD → MMDD
        parts = str(date_str).split("-")
        if len(parts) >= 3:
            stamp = f"{parts[1]}{parts[2]}"
    if not stamp:
        now = datetime.now(timezone.utc)
        stamp = f"{now.month:02d}{now.day:02d}"
    return f"#SN{netuid}-{stamp}"


def _spread_note(benches: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(benches) < 2:
        return {"pts": 0, "outlier_bench": None, "note": ""}
    positions = [(b["key"], float(b["position"])) for b in benches]
    lo = min(positions, key=lambda x: x[1])
    hi = max(positions, key=lambda x: x[1])
    pts = int(round(abs(hi[1] - lo[1])))
    # Outlier = farthest from the centroid
    centroid = sum(p for _, p in positions) / len(positions)
    outlier = max(positions, key=lambda x: abs(x[1] - centroid))
    label = next((b["label"] for b in benches if b["key"] == outlier[0]), outlier[0])
    note = f"{pts}pt swing, {label} outlier" if pts else "Tight bench"
    return {"pts": pts, "outlier_bench": outlier[0], "note": note}


def _load_soul_weights() -> Dict[str, float]:
    try:
        from internal.council.weights import load_weights

        w = load_weights()
        if isinstance(w, dict):
            return {k: float(w.get(k, 1.0)) for k, _, _ in BENCH_DEFS}
    except Exception as exc:
        logger.debug("tribunal weights load skipped: %s", exc)
    return {k: 1.0 for k, _, _ in BENCH_DEFS}


def build_tribunal_block(daily_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(daily_payload, dict) or not daily_payload:
        return _empty_tribunal(kind="cold", reason="No council payload")

    block, role = _active_block(daily_payload)
    action = daily_payload.get("action") or (block or {}).get("action") or "HOLD"
    verdict = _verdict_from_action(action)
    reason = str(
        daily_payload.get("reason")
        or daily_payload.get("hold_reason")
        or ""
    ).strip()

    status = str(daily_payload.get("status") or "").lower()
    if status in ("pending", "forming", "timeout") and not block:
        return _empty_tribunal(kind="forming", reason=reason or "Council still forming")

    if block is None:
        return _empty_tribunal(kind="forming", reason=reason or "No name on the table")

    subnet = _subnet_from_block(block)
    experts = _extract_experts(block)
    if not experts:
        # Some payloads nest scores one level up
        experts = _extract_experts(daily_payload)

    conviction = _as_pct(
        block.get("final_confidence", block.get("confidence", block.get("conviction", 0)))
    )
    weights = _load_soul_weights()

    benches: List[Dict[str, Any]] = []
    for key, label, chip in BENCH_DEFS:
        if key not in experts:
            continue
        stance, conf, position = _stance_from_score(experts[key])
        benches.append(
            {
                "key": key,
                "label": label,
                "chip": chip,
                "stance": stance,
                "confidence": conf,
                "score": round(experts[key], 4),
                "weight": round(float(weights.get(key, 1.0)), 4),
                "position": round(position, 1),
            }
        )

    if not benches:
        empty = _empty_tribunal(kind="forming", reason=reason or "Bench scores not ready")
        empty["subnet"] = subnet
        empty["case_id"] = _case_id(subnet, daily_payload.get("date"))
        empty["conviction_pct"] = conviction
        empty["verdict"] = verdict
        empty["horizon"] = str(daily_payload.get("time_horizon") or daily_payload.get("horizon") or "24h")
        empty["resolves_in"] = daily_payload.get("resolves_in")
        return empty

    # Weighted centroid on the spectrum (soul weights)
    w_sum = sum(float(b["weight"]) for b in benches) or 1.0
    centroid = sum(float(b["position"]) * float(b["weight"]) for b in benches) / w_sum

    concur_n = sum(1 for b in benches if b["stance"] == verdict)
    spread = _spread_note(benches)

    # Kind: published LONG/SHORT = sealed; HOLD with gate reason = gated; else forming
    if verdict in ("BUY", "SELL") and role == "pick":
        kind = "sealed"
        session = "Council in session"
        gate_passed = True
    elif verdict == "HOLD" and reason:
        kind = "gated"
        session = "Case open — gate held"
        gate_passed = False
    elif role == "candidate":
        kind = "gated"
        session = "Case open — gate held"
        gate_passed = False
    else:
        kind = "forming"
        session = "Council warming up"
        gate_passed = False

    flip = ""
    if not gate_passed and reason:
        flip = reason
    elif not gate_passed:
        flip = "Conviction must clear the publish gate for a sealed call"

    return {
        "case_id": _case_id(subnet, daily_payload.get("date")),
        "verdict": verdict,
        "verdict_kind": kind,
        "conviction_pct": conviction,
        "concur": {"n": concur_n, "of": len(benches)},
        "spread": spread,
        "benches": benches,
        "centroid": round(centroid, 1),
        "gate": {
            "passed": gate_passed,
            "reason": reason,
            "flip_condition": flip,
        },
        "subnet": subnet,
        "sealed_at": daily_payload.get("generated_at") or daily_payload.get("timestamp_utc"),
        "resolves_in": daily_payload.get("resolves_in"),
        "horizon": str(daily_payload.get("time_horizon") or daily_payload.get("horizon") or "24h"),
        "session_label": session,
        "temporal_badge": daily_payload.get("temporal_badge"),
    }


def attach_tribunal_to_daily_pick(
    daily_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    base = dict(daily_payload) if isinstance(daily_payload, dict) else {}
    try:
        base["tribunal"] = build_tribunal_block(base)
    except Exception as exc:
        logger.warning("dpick tribunal attach failed: %s", exc)
        base["tribunal"] = _empty_tribunal(kind="forming", reason="Tribunal attach failed")
    return base
