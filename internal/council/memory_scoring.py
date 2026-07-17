"""Soft memory features for pick scoring (§30-6, §30-7)."""

from __future__ import annotations

from typing import Any, Dict, Optional

_DISPOSITION_CAP = 3.0
_SCENARIO_CAP = 2.0

_BULLISH = frozenset({"long", "buy", "accumulate", "bull", "bullish"})
_BEARISH = frozenset({"short", "sell", "reduce", "bear", "bearish"})


def _netuid_key(sn: Dict[str, Any]) -> Optional[int]:
    for key in ("netuid", "id", "subnet_id"):
        val = sn.get(key)
        if val is None:
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _load_disposition(netuid: int) -> Optional[Dict[str, Any]]:
    try:
        from internal.council.weights import _load_raw

        raw = _load_raw()
        sms = raw.get("soul_map_state") or raw.get("adversarial_state") or {}
        for block_key in ("message_intel_dispositions", "pump_dispositions"):
            block = sms.get(block_key)
            if not isinstance(block, dict):
                continue
            payload = block.get(str(netuid)) or block.get(netuid)
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return None


def disposition_score_adjustment(sn: Dict[str, Any]) -> float:
    """Capped ±3 pt tilt from message-intel / pump dispositions."""
    netuid = _netuid_key(sn or {})
    if netuid is None:
        return 0.0
    disp = _load_disposition(netuid)
    if not disp:
        return 0.0
    action = str(
        disp.get("recommended_action") or disp.get("action") or ""
    ).lower().strip()
    if not action:
        return 0.0
    conviction = float(disp.get("conviction") or 50.0)
    strength = min(1.0, max(0.0, conviction / 100.0))
    if action in _BULLISH:
        return round(_DISPOSITION_CAP * strength, 2)
    if action in _BEARISH:
        return round(-_DISPOSITION_CAP * strength, 2)
    return 0.0


def scenario_outcome_adjustment(
    sn: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> float:
    """Capped ±2 pt tilt from resolved scenario memory for this netuid."""
    netuid = _netuid_key(sn or {})
    if netuid is None:
        return 0.0
    try:
        from internal.council import scenario_memory

        scenarios = scenario_memory.get_scenarios(limit=300)
    except Exception:
        return 0.0

    matching = []
    for scen in scenarios or []:
        if not isinstance(scen, dict):
            continue
        features = scen.get("features") if isinstance(scen.get("features"), dict) else {}
        sid = features.get("netuid", features.get("subnet_id"))
        try:
            if int(sid) != netuid:
                continue
        except (TypeError, ValueError):
            continue
        outcome = str(scen.get("outcome") or "").lower()
        if outcome in {"correct", "wrong", "hit", "miss"}:
            matching.append(outcome)

    if len(matching) < 2:
        return 0.0

    hits = sum(1 for o in matching if o in {"correct", "hit"})
    rate = hits / len(matching)
    # ponytail: ±2 pt cap; upgrade path = regime-conditioned retrieval
    return round(max(-_SCENARIO_CAP, min(_SCENARIO_CAP, (rate - 0.5) * 8.0)), 2)
