"""
SimiVision Signal Engine — Legendary Edition

Builds the rich signal object required by the SimiVision Legendary Edition:
- netuid
- name (canonical, read directly from registry.json)
- rank
- conviction (0-100)
- rationale
- delta (+/-/stable) and delta_value
- freshness
- source
- status (Operative / Dimmed / Hibernating / Error)

The engine exposes the top-N scored subnets and persists the last computed
conviction per subnet so deltas are meaningful across runs.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.freshness import registry_freshness, soul_map_freshness

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
STAKE_THRESHOLD_TAO = float(os.environ.get("STAKE_THRESHOLD_TAO", "400000"))

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

def _human_freshness(iso_timestamp):
    if not iso_timestamp:
        return "Unknown"
    parsed = _parse_iso(iso_timestamp)
    if not parsed:
        return "Unknown"
    age = int((datetime.now(timezone.utc) - parsed).total_seconds())
    if age < 60:
        return "Just now"
    if age < 3600:
        return f"Updated {age // 60} min ago"
    if age < 86400:
        return f"Updated {age // 3600} h ago"
    return f"Updated {age // 86400} d ago"

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def _load_registry(registry_path=REGISTRY_PATH):
    return _load_json(registry_path)

def _filter_low_mid_cap_subnets(registry, stake_threshold_tao=STAKE_THRESHOLD_TAO):
    filtered = {}
    for sid_str, data in registry.items():
        try:
            stake = data.get("staking_data", {}).get("total_stake", 0)
            if stake < stake_threshold_tao:
                filtered[sid_str] = data
        except (ValueError, TypeError):
            filtered[sid_str] = data
    return filtered

def _load_last_convictions(soul_map_path=SOUL_MAP_PATH):
    soul_map = _load_json(soul_map_path)
    return soul_map.get("simivision_convictions", {})

def _persist_convictions(convictions, soul_map_path=SOUL_MAP_PATH):
    soul_map = _load_json(soul_map_path)
    soul_map["simivision_convictions"] = {str(k): v for k, v in convictions.items()}
    soul_map["simivision_convictions_updated_at"] = _now_iso()
    _save_json(soul_map_path, soul_map)

def _load_council_decisions(soul_map_path=SOUL_MAP_PATH):
    soul_map = _load_json(soul_map_path)
    last_output = soul_map.get("soul_map_state", {}).get("last_selector_output", {})
    return last_output.get("decisions", [])

def _synthesize_decision(netuid, registry_item):
    """Generate a neutral decision when no Council decision exists for a subnet."""
    emission = registry_item.get("emission", 0.0) or 0.0
    mentions = registry_item.get("social_mentions", 0) or 0
    is_overvalued = registry_item.get("is_overvalued", False)

    quant_score = 0.85 if emission > 1.0 else 0.4 if emission < 0.2 else 0.75
    hype_score = 0.9 if mentions > 1000 else 0.3 if mentions < 100 else 0.65
    dark_horse_score = 0.2 if is_overvalued else 0.8
    technical_score = 0.5

    consensus_score = round(
        quant_score * 0.3 + hype_score * 0.25 + dark_horse_score * 0.2 + technical_score * 0.25, 4
    )

    if consensus_score >= 0.75:
        action = "accumulate"
    elif consensus_score <= 0.4:
        action = "reduce"
    else:
        action = "hold"

    return {
        "subnet_id": netuid,
        "consensus_score": consensus_score,
        "recommended_action": action,
        "expert_breakdown": {
            "quant": {"score": quant_score, "metrics": {"emission_stability": "high" if quant_score >= 0.7 else "low", "performance_index": quant_score * 100}},
            "hype": {"score": hype_score, "sentiment": "bullish" if hype_score >= 0.7 else "bearish" if hype_score < 0.4 else "neutral", "metrics": {"social_volume": mentions, "hype_index": hype_score * 100}},
            "dark_horse": {"score": dark_horse_score, "signal": "sell" if is_overvalued else "buy", "metrics": {"dark_horse_index": dark_horse_score * 100}},
            "technical": {"score": technical_score, "signal": "hold", "metrics": {"active_signals": []}},
        },
        "synthesized": True,
    }

def _compute_conviction(decision, registry_item):
    consensus = decision.get("consensus_score", 0.5)
    base = min(100.0, max(0.0, consensus * 70.0))
    rank = registry_item.get("emission_rank")
    rank_bonus = 0.0
    if isinstance(rank, int):
        if rank <= 10: rank_bonus = 15.0
        elif rank < 25: rank_bonus = 10.0
        elif rank < 50: rank_bonus = 5.0
    social = registry_item.get("social_mentions", 0) or 0
    social_bonus = 10.0 if social > 1500 else 5.0 if social > 1000 else 0.0
    overvalued = registry_item.get("is_overvalued", False)
    penalty = 10.0 if overvalued else 0.0
    tiebreaker = 0.0
    if isinstance(rank, int) and rank > 0:
        tiebreaker = min(0.99, 1.0 / rank)
    conviction = base + rank_bonus + social_bonus - penalty + tiebreaker
    indicator_bonus = 0.0
    indicator_phrases = []
    breakdown = decision.get("expert_breakdown", {})
    technical = breakdown.get("technical", {})
    active_signals = technical.get("metrics", {}).get("active_signals", [])
    bullish_signals = {"rsi_oversold_reversal", "macd_bullish_cross", "stochastic_oversold_reversal", "williams_oversold_exit"}
    bearish_signals = {"rsi_overbought_reversal", "macd_bearish_cross"}
    bullish_count = sum(1 for s in active_signals if s in bullish_signals)
    bearish_count = sum(1 for s in active_signals if s in bearish_signals)
    if bullish_count > 0:
        indicator_bonus += 5.0
        indicator_phrases.extend([s.replace("_", " ") for s in active_signals if s in bullish_signals])
    if bearish_count > 0:
        indicator_bonus -= 5.0
        indicator_phrases.extend([s.replace("_", " ") for s in active_signals if s in bearish_signals])
    if bullish_count >= 2:
        indicator_bonus += 3.0
        indicator_phrases.append("bullish confluence")
    conviction += indicator_bonus
    return round(min(100.0, max(0.0, conviction)), 2), indicator_phrases

def _compute_delta(netuid, conviction, last_convictions):
    last = last_convictions.get(str(netuid))
    if last is None:
        return "stable", 0.0
    diff = round(conviction - last, 2)
    if abs(diff) < 0.01:
        return "stable", 0.0
    return ("+", diff) if diff > 0 else ("-", abs(diff))

def _build_rationale(decision, registry_item, conviction, status):
    if status == "Dimmed":
        return "Live but weak."
    action = decision.get("recommended_action", "hold")
    breakdown = decision.get("expert_breakdown", {})
    quant = breakdown.get("quant", {})
    hype = breakdown.get("hype", {})
    dark_horse = breakdown.get("dark_horse", {})
    technical = breakdown.get("technical", {})
    quant_label = (quant.get("metrics") or {}).get("emission_stability", "neutral")
    hype_label = hype.get("sentiment", "neutral")
    dark_horse_label = dark_horse.get("signal", "hold")
    overvalued = registry_item.get("is_overvalued", False)
    quant_phrase = {"high": "strong emission stability", "medium": "stable emissions", "low": "weak emission stability"}.get(quant_label, f"emission stability {quant_label}")
    hype_phrase = {"bullish": "bullish social sentiment", "neutral": "neutral social sentiment", "bearish": "bearish social sentiment"}.get(hype_label, f"sentiment {hype_label}")
    dark_horse_phrase = {"buy": "dark horse buy signal", "hold": "dark horse hold signal", "sell": "dark horse sell signal"}.get(dark_horse_label, f"dark horse {dark_horse_label}")
    if action == "accumulate":
        opener = "Strong consensus to accumulate"
    elif action == "reduce":
        opener = "Consensus favors reduction"
    else:
        opener = "Consensus is neutral"
    parts = [opener, quant_phrase, hype_phrase, dark_horse_phrase]
    active_signals = technical.get("metrics", {}).get("active_signals", [])
    if active_signals:
        parts.append("; ".join(s.replace("_", " ") for s in active_signals))
    if overvalued:
        parts.append("overvalued")
    return " ".join(parts)

def _build_signal(netuid, decision, registry_item, last_convictions):
    conviction, indicator_phrases = _compute_conviction(decision, registry_item)
    delta_symbol, delta_value = _compute_delta(netuid, conviction, last_convictions)
    rationale = _build_rationale(decision, registry_item, conviction, "Operative")
    status = "Operative" if conviction >= 50 else "Dimmed" if conviction >= 25 else "Hibernating"
    return {"netuid": netuid, "name": registry_item.get("name", f"Subnet {netuid}"), "rank": registry_item.get("emission_rank"), "conviction": conviction, "rationale": rationale, "delta": delta_symbol, "delta_value": delta_value, "freshness": _human_freshness(registry_item.get("updated_at")), "source": registry_item.get("source", "taomarketcap"), "status": status, "indicator_signals": indicator_phrases}

def generate_signals(registry=None, top_n=10, soul_map_path=SOUL_MAP_PATH):
    if registry is None:
        registry = _load_registry()
    registry = _filter_low_mid_cap_subnets(registry)
    decisions = _load_council_decisions(soul_map_path)
    last_convictions = _load_last_convictions(soul_map_path)
    signals = []
    for sid_str, item in registry.items():
        try:
            netuid = int(sid_str)
        except (ValueError, TypeError):
            continue
        decision = next((d for d in decisions if d.get("subnet_id") == netuid), None)
        if decision is None:
            decision = _synthesize_decision(netuid, item)
        signal = _build_signal(netuid, decision, item, last_convictions)
        signals.append(signal)
    signals.sort(key=lambda s: s["conviction"], reverse=True)
    top_signals = signals[:top_n]
    convictions_map = {s["netuid"]: s["conviction"] for s in signals}
    _persist_convictions(convictions_map, soul_map_path)
    return top_signals
