"""Per-subnet judge scoring for the council dashboard."""

from __future__ import annotations

import json
import os
import statistics
from typing import Any, Dict, List, Optional

from internal.chain_client import ChainClient
from internal.judges.judges import ECHO, ORACLE, PULSE

DATA_DIR = os.environ.get("DATA_DIR", "data")


def _flat_subnet_for_judges(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Subnet dict for judge evaluate(subnet=...) — not nested under prediction."""
    return {
        "price": subnet.get("price", 0),
        "apy": subnet.get("apy", 0),
        "emission": subnet.get("emission", subnet.get("emissions", 0)),
        "stake": subnet.get("stake", subnet.get("total_stake", 0)),
        "volume": subnet.get("volume", subnet.get("volume_24h", 0)),
        "price_change_24h": subnet.get("price_change_24h", subnet.get("change_24h", 0)),
        "price_change_7d": subnet.get("price_change_7d", subnet.get("change_7d", 0)),
        "social_mentions": subnet.get("social_mentions", subnet.get("mentions", 0)),
        "social_sentiment": subnet.get("social_sentiment", subnet.get("sentiment", 0.5)),
        "yield_trap": subnet.get("yield_trap"),
        "blockmachine_alpha_price": subnet.get("blockmachine_alpha_price"),
        "blockmachine_price_delta": subnet.get("blockmachine_price_delta"),
    }


def _prediction_for_judges(
    subnet: Dict[str, Any],
    *,
    predicted_pct: float,
    direction: str,
    signal_source: str = "dashboard",
) -> Dict[str, Any]:
    return {
        "subnet": subnet.get("name", f"Subnet {subnet.get('netuid')}"),
        "netuid": subnet.get("netuid"),
        "predicted_pct": predicted_pct,
        "direction": direction,
        "signal_source": signal_source,
    }


def _impact_direction(value: float, *, bullish_above: float = 0.0) -> str:
    if value > bullish_above:
        return "bullish"
    if value < -bullish_above:
        return "bearish"
    return "neutral"


def _signal_impact_from_subnet(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Dashboard signal_impact — enough voices for Echo to differentiate subnets."""
    chg = float(subnet.get("price_change_24h", subnet.get("change_24h", 0)) or 0)
    chg7 = float(subnet.get("price_change_7d", subnet.get("change_7d", 0)) or 0)
    direction = _impact_direction(chg)
    impacts: List[Dict[str, Any]] = []
    if chg != 0:
        impacts.append(
            {
                "direction": direction,
                "magnitude_pct": abs(chg),
                "signal": "price_change_24h",
            }
        )
    if chg7 != 0:
        impacts.append(
            {
                "direction": _impact_direction(chg7),
                "magnitude_pct": abs(chg7),
                "signal": "price_change_7d",
            }
        )
    try:
        apy = float(subnet.get("apy", 0) or 0)
    except (TypeError, ValueError):
        apy = 0.0
    if apy > 0:
        impacts.append(
            {
                "direction": "bullish" if apy >= 0.12 else "neutral" if apy >= 0.05 else "bearish",
                "magnitude_pct": min(apy * 100, 10.0),
                "signal": "apy_tier",
            }
        )
    try:
        volume = float(subnet.get("volume", subnet.get("volume_24h", 0)) or 0)
    except (TypeError, ValueError):
        volume = 0.0
    if volume > 0:
        impacts.append(
            {
                "direction": "bullish" if volume >= 100_000 else "neutral" if volume >= 1_000 else "bearish",
                "magnitude_pct": min(max(volume, 1.0) ** 0.25, 10.0),
                "signal": "volume_tier",
            }
        )
    sentiment = subnet.get("social_sentiment", subnet.get("sentiment"))
    if sentiment is not None:
        try:
            s = float(sentiment)
            impacts.append(
                {
                    "direction": "bullish" if s >= 0.55 else "bearish" if s <= 0.45 else "neutral",
                    "magnitude_pct": abs(s - 0.5) * 10,
                    "signal": "social_sentiment",
                }
            )
        except (TypeError, ValueError):
            pass
    return {
        "impacts": impacts,
        "net_direction": direction,
        "net_predicted_pct": chg,
    }


def _oracle_signals(
    flat: Dict[str, Any],
    signal_impact: Dict[str, Any],
    prediction: Dict[str, Any],
) -> Dict[str, Any]:
    """Observable drivers behind Oracle score (dashboard honesty, not hardcoded)."""
    chg24 = float(flat.get("price_change_24h", 0) or 0)
    chg7 = float(flat.get("price_change_7d", chg24) or 0)
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    if predicted_pct > 0:
        align_24h = chg24 >= 0
        align_7d = chg7 >= -1.0
    elif predicted_pct < 0:
        align_24h = chg24 <= 0
        align_7d = chg7 <= 1.0
    else:
        align_24h = align_7d = True
    impacts = signal_impact.get("impacts") or []
    directional = sum(
        1 for item in impacts if item.get("direction") in ("bullish", "bearish")
    )
    completeness = sum(
        1 for key in ("price", "apy", "emission") if flat.get(key) not in (None, "", 0)
    )
    return {
        "price_align_24h": align_24h,
        "price_align_7d": align_7d,
        "fundamentals_present": completeness,
        "has_volume": flat.get("volume") not in (None, "", 0),
        "has_social": flat.get("social_mentions") is not None,
        "yield_trap": bool(flat.get("yield_trap")),
        "directional_impacts": directional,
        "impact_count": len(impacts),
    }


def score_subnet(
    netuid: int,
    subnet: Dict[str, Any],
    market_context: Optional[Dict] = None,
    chain_client: Optional[ChainClient] = None,
) -> Dict[str, Any]:
    """Score a single subnet with all three judges + consensus."""
    name = subnet.get("name", f"Subnet {netuid}")
    flat = _flat_subnet_for_judges(subnet)
    chg = float(flat.get("price_change_24h", 0) or 0)
    predicted_pct = chg if chg != 0 else 0.5
    direction = "up" if predicted_pct >= 0 else "down"
    signal_impact = _signal_impact_from_subnet(subnet)
    prediction = _prediction_for_judges(
        subnet, predicted_pct=predicted_pct, direction=direction
    )

    try:
        oracle_result = ORACLE.evaluate(
            prediction, signal_impact=signal_impact, subnet=flat
        )
        oracle_score = oracle_result.get("score", 0.5)
        oracle_confidence = oracle_result.get("confidence", 0.5)
        oracle_degraded = False
    except Exception:
        oracle_score = 0.5
        oracle_confidence = 0.0
        oracle_degraded = True

    if not any(
        subnet.get(k)
        for k in ("price", "apy", "emission", "emissions", "stake", "total_stake")
    ):
        oracle_degraded = True

    try:
        echo_result = ECHO.evaluate(
            prediction, signal_impact=signal_impact, expert_weights=None
        )
        echo_score = echo_result.get("score", 0.5)
        echo_confidence = echo_result.get("confidence", 0.5)
        echo_degraded = False
        if not subnet.get("social_mentions") and not subnet.get("mentions"):
            echo_degraded = True
    except Exception:
        echo_score = 0.5
        echo_confidence = 0.0
        echo_degraded = True

    pulse_subnet = dict(flat)
    on_chain_price_delta = None
    if chain_client is not None:
        try:
            if chain_client.is_healthy():
                alpha_price = chain_client.get_alpha_price(netuid)
                if alpha_price and alpha_price > 0:
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
                    cached[key] = alpha_price
                    try:
                        os.makedirs(DATA_DIR, exist_ok=True)
                        with open(cache_path, "w") as f:
                            json.dump(cached, f)
                    except Exception:
                        pass
                    pulse_subnet["blockmachine_alpha_price"] = alpha_price
                    if on_chain_price_delta is not None:
                        pulse_subnet["blockmachine_price_delta"] = on_chain_price_delta
        except Exception:
            pass

    try:
        pulse_result = PULSE.evaluate(
            prediction, signal_impact=signal_impact, subnet=pulse_subnet
        )
        pulse_score = pulse_result.get("score", 0.5)
        pulse_confidence = pulse_result.get("confidence", 0.5)
        pulse_degraded = False
        if chain_client and (on_chain_price_delta is None):
            pulse_degraded = True
    except Exception:
        pulse_score = 0.5
        pulse_confidence = 0.0
        pulse_degraded = True

    scores = [oracle_score, echo_score, pulse_score]
    try:
        from internal.judges.weights import normalized_judge_weights

        jw = normalized_judge_weights()
    except Exception:
        from internal.judges.weights import DEFAULT_JUDGE_WEIGHTS

        jw = dict(DEFAULT_JUDGE_WEIGHTS)
    consensus_score = (
        oracle_score * jw["oracle"]
        + echo_score * jw["echo"]
        + pulse_score * jw["pulse"]
    )
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
    consensus_confidence = (
        oracle_confidence * jw["oracle"]
        + echo_confidence * jw["echo"]
        + pulse_confidence * jw["pulse"]
    )
    return {
        "netuid": netuid,
        "name": name,
        "oracle": {
            "score": round(oracle_score, 4),
            "confidence": round(oracle_confidence, 4),
            "signals": _oracle_signals(flat, signal_impact, prediction),
            "degraded": oracle_degraded,
        },
        "echo": {
            "score": round(echo_score, 4),
            "confidence": round(echo_confidence, 4),
            "signals": {"signal_count": len(signal_impact.get("impacts") or [])},
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
    subnets: Optional[List[Dict[str, Any]]] = None,
    market_context: Optional[Dict] = None,
    use_chain: bool = True,
) -> List[Dict[str, Any]]:
    """Score all subnets and return sorted by consensus score descending."""
    if subnets is None:
        try:
            from fetchers.merged_data import get_merged_subnet_data

            subnets = get_merged_subnet_data()
            if not subnets:
                from fetchers.taomarketcap import get_all_subnets

                subnets = get_all_subnets()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Failed to fetch merged data: %s", exc)
            subnets = []

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
            results.append(
                {
                    "netuid": netuid,
                    "name": subnet.get("name", f"Subnet {netuid}"),
                    "oracle": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                    "echo": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                    "pulse": {"score": 0.5, "confidence": 0, "signals": {}, "degraded": True},
                    "consensus": {
                        "score": 0.5,
                        "agreement": 1,
                        "verdict": "neutral",
                        "confidence": 0,
                        "contested": False,
                    },
                }
            )

    results.sort(key=lambda r: r["consensus"]["score"], reverse=True)
    return results
