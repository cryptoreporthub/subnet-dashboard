"""Per-subnet judge scoring for the council dashboard."""

from __future__ import annotations

import json
import os
import statistics
from typing import Any, Dict, List, Optional

from internal.chain_client import ChainClient
from internal.judges import oracle_judge, echo_judge, pulse_judge
from internal.judges.judges import ORACLE, ECHO, PULSE

DATA_DIR = os.environ.get("DATA_DIR", "data")


def score_subnet(
    netuid: int,
    subnet: Dict[str, Any],
    market_context: Optional[Dict] = None,
    chain_client: Optional[ChainClient] = None,
) -> Dict[str, Any]:
    """Score a single subnet with all three judges + consensus."""
    name = subnet.get("name", f"Subnet {netuid}")

    # --- Oracle: evaluate fundamentals ---
    oracle_prediction = {
        "subnet": name,
        "netuid": netuid,
        "signal_impact": 0.5,  # neutral baseline
        "subnet_data": {
            "price": subnet.get("price", 0),
            "apy": subnet.get("apy", 0),
            "emission": subnet.get("emission", subnet.get("emissions", 0)),
            "stake": subnet.get("stake", subnet.get("total_stake", 0)),
            "delegated": subnet.get("delegated", subnet.get("delegation_count", 0)),
            "owner_count": subnet.get("owner_count", subnet.get("owners", 0)),
            "registration_cost": subnet.get("registration_cost", subnet.get("cost", 0)),
            "age_blocks": subnet.get("age_blocks", subnet.get("blocks_since_registration", subnet.get("age", 0))),
        },
        "prices": {"current": subnet.get("price", 0)},
    }
    try:
        oracle_result = ORACLE.evaluate(oracle_prediction)
        oracle_score = oracle_result.get("score", 0.5)
        oracle_confidence = oracle_result.get("confidence", 0.5)
        oracle_degraded = False
    except Exception:
        oracle_score = 0.5
        oracle_confidence = 0.0
        oracle_degraded = True

    # Degrade Oracle when no fundamental data is available.
    if not any(
        subnet.get(k)
        for k in ("price", "apy", "emission", "emissions", "stake", "total_stake")
    ):
        oracle_degraded = True

    # --- Echo: evaluate signal consensus ---
    echo_prediction = {
        "subnet": name,
        "netuid": netuid,
        "signal_impact": float(subnet.get("signal_impact", subnet.get("sentiment", 0.5))),
        "subnet_data": {
            "price_change_24h": subnet.get("price_change_24h", subnet.get("change_24h", 0)),
            "price_change_7d": subnet.get("price_change_7d", subnet.get("change_7d", 0)),
            "volume": subnet.get("volume", subnet.get("volume_24h", 0)),
            "social_mentions": subnet.get("social_mentions", subnet.get("mentions", 0)),
            "social_sentiment": subnet.get("social_sentiment", subnet.get("sentiment", 0.5)),
            "active_signals": subnet.get("active_signals", subnet.get("signals", 0)),
        },
    }
    try:
        echo_result = ECHO.evaluate(echo_prediction)
        echo_score = echo_result.get("score", 0.5)
        echo_confidence = echo_result.get("confidence", 0.5)
        echo_degraded = False
        if not subnet.get("social_mentions") and not subnet.get("mentions"):
            echo_degraded = True
    except Exception:
        echo_score = 0.5
        echo_confidence = 0.0
        echo_degraded = True

    # --- Pulse: evaluate momentum + optional Blockmachine ---
    pulse_subnet_data = {
        "price_change_24h": subnet.get("price_change_24h", subnet.get("change_24h", 0)),
        "volume": subnet.get("volume", subnet.get("volume_24h", 0)),
        "price": subnet.get("price", 0),
    }
    # Try Blockmachine on-chain alpha price
    on_chain_price_delta = None
    if chain_client is not None:
        try:
            if chain_client.is_healthy():
                alpha_price = chain_client.get_alpha_price(netuid)
                if alpha_price and alpha_price > 0:
                    # Load cached price
                    cache_path = os.path.join(DATA_DIR, "price_cache.json")
                    cached = {}
                    if os.path.exists(cache_path):
                        try:
                            with open(cache_path) as f:
                                cached = json.load(f)
                        except Exception:
                            pass
                    key = f"{netuid}.alpha"
                    prev = cached.get(key)
                    if prev and prev > 0:
                        on_chain_price_delta = (alpha_price - prev) / prev
                    # Update cache
                    cached[key] = alpha_price
                    try:
                        os.makedirs(DATA_DIR, exist_ok=True)
                        with open(cache_path, "w") as f:
                            json.dump(cached, f)
                    except Exception:
                        pass
                    pulse_subnet_data["blockmachine_alpha_price"] = alpha_price
                    if on_chain_price_delta is not None:
                        pulse_subnet_data["blockmachine_price_delta"] = on_chain_price_delta
        except Exception:
            pass  # degraded handled below

    pulse_prediction = {
        "subnet": name,
        "netuid": netuid,
        "signal_impact": 0.5,
        "subnet_data": pulse_subnet_data,
        "prices": {"current": subnet.get("price", 0)},
    }
    try:
        pulse_result = PULSE.evaluate(pulse_prediction)
        pulse_score = pulse_result.get("score", 0.5)
        pulse_confidence = pulse_result.get("confidence", 0.5)
        pulse_degraded = False
        if chain_client and (on_chain_price_delta is None):
            pulse_degraded = True  # RPC was attempted but failed
    except Exception:
        pulse_score = 0.5
        pulse_confidence = 0.0
        pulse_degraded = True

    # --- Consensus ---
    scores = [oracle_score, echo_score, pulse_score]
    # Weighted average: oracle 0.35, echo 0.30, pulse 0.35
    consensus_score = oracle_score * 0.35 + echo_score * 0.30 + pulse_score * 0.35
    # Agreement = 1 - stddev/clamp
    if len(scores) > 1:
        stddev = statistics.stdev(scores)
        agreement = max(0.0, min(1.0, 1.0 - stddev / 0.5))
    else:
        agreement = 1.0

    if all(s > 0.65 for s in scores):
        verdict = "long"
    elif all(s < 0.35 for s in scores):
        verdict = "short"
    else:
        verdict = "neutral"

    contested = agreement < 0.5
    consensus_confidence = sum(
        [oracle_confidence * 0.35, echo_confidence * 0.30, pulse_confidence * 0.35]
    )

    return {
        "netuid": netuid,
        "name": name,
        "oracle": {
            "score": round(oracle_score, 4),
            "confidence": round(oracle_confidence, 4),
            "signals": {"fundamentals": True},
            "degraded": oracle_degraded,
        },
        "echo": {
            "score": round(echo_score, 4),
            "confidence": round(echo_confidence, 4),
            "signals": {"signal_count": 1, "agreement_ratio": 0.5},
            "degraded": echo_degraded,
        },
        "pulse": {
            "score": round(pulse_score, 4),
            "confidence": round(pulse_confidence, 4),
            "signals": {
                "on_chain_price_delta": on_chain_price_delta,
                "on_chain_degraded": pulse_degraded if chain_client else False,
            },
            "degraded": pulse_degraded,
        },
        "consensus": {
            "score": round(consensus_score, 4),
            "agreement": round(agreement, 4),
            "verdict": verdict,
            "confidence": round(consensus_confidence, 4),
            "contested": contested,
        },
    }


def score_all_subnets(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict] = None,
    use_chain: bool = True,
) -> List[Dict[str, Any]]:
    """Score all subnets and return sorted by consensus score descending."""
    chain_client = None
    if use_chain:
        try:
            chain_client = ChainClient(timeout=10)
        except Exception:
            pass

    results = []
    for subnet in subnets:
        netuid = subnet.get("netuid", subnet.get("id", 0))
        try:
            result = score_subnet(netuid, subnet, market_context, chain_client)
            results.append(result)
        except Exception:
            results.append({
                "netuid": netuid,
                "name": subnet.get("name", f"Subnet {netuid}"),
                "oracle": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                "echo": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                "pulse": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                "consensus": {"score": 0.5, "agreement": 1, "verdict": "neutral", "confidence": 0, "contested": False},
            })

    results.sort(key=lambda r: r["consensus"]["score"], reverse=True)
    return results
