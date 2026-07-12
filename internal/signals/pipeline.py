"""Live signal generation from council scoring (read-only, Phase L slice 1)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.signals.store import EXPERTS, SignalStore

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_subnets() -> List[Dict[str, Any]]:
    try:
        from fetchers.taomarketcap import get_all_subnets

        live = get_all_subnets()
        if live:
            deduped: Dict[Any, Dict[str, Any]] = {}
            for sn in live:
                deduped.setdefault(sn.get("netuid"), sn)
            return list(deduped.values())
    except Exception as exc:
        logger.warning("Live subnet fetch failed: %s", exc)
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [dict(v, netuid=v.get("id", int(k))) for k, v in data.items()]
    except Exception as exc:
        logger.warning("Registry load failed: %s", exc)
        return []


def _market_context() -> Dict[str, Any]:
    try:
        from internal.council.weights import load_weights

        weights = load_weights()
    except Exception:
        weights = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    subnets = load_subnets()
    changes = []
    for sn in subnets:
        try:
            changes.append(float(sn.get("price_change_24h", 0) or 0))
        except (TypeError, ValueError):
            continue
    return {
        "tao_change_24h": sum(changes) / len(changes) if changes else 0.0,
        "weights": weights,
    }


def _signal_type(total_score: float, hot: Dict[str, Any], sell: Dict[str, Any]) -> str:
    if sell.get("active"):
        return "sell"
    if hot.get("active") and total_score >= 50:
        return "buy"
    if total_score >= 60:
        return "buy"
    if total_score <= 40:
        return "sell"
    return "neutral"


def _source_expert(experts: Dict[str, Any]) -> str:
    core = {k: float(experts.get(k, 0) or 0) for k in EXPERTS}
    return max(core, key=core.get)


def _evidence(sn: Dict[str, Any], hot: Dict[str, Any], sell: Dict[str, Any], score: Dict[str, Any]) -> str:
    parts: List[str] = []
    if hot.get("active") and hot.get("reasons"):
        parts.append("; ".join(hot["reasons"][:2]))
    if sell.get("active") and sell.get("reasons"):
        parts.append("; ".join(sell["reasons"][:2]))
    regime = (score.get("scenario_tags") or {}).get("regime")
    if regime:
        parts.append(f"regime={regime}")
    try:
        parts.append(f"24h={float(sn.get('price_change_24h', 0)):+.1f}%")
    except (TypeError, ValueError):
        pass
    return " · ".join(parts) if parts else f"score={score.get('total_score', 0):.1f}"


def build_signal(sn: Dict[str, Any], market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from internal.council.state_vector import (
        _compute_hot_signals,
        _compute_sell_signals,
        _compute_technical_indicators,
        _detect_oversold_convergence,
        score_subnet_for_hour,
    )

    market_context = market_context or _market_context()
    netuid = sn.get("netuid") or sn.get("id")
    try:
        indicators = _compute_technical_indicators(sn)
        convergence = _detect_oversold_convergence(indicators)
        hot = _compute_hot_signals(sn, indicators, convergence)
        sell = _compute_sell_signals(sn, indicators, convergence)
        score = score_subnet_for_hour(sn, market_context)
    except Exception as exc:
        logger.warning("Signal build failed SN%s: %s", netuid, exc)
        return {
            "subnet_id": netuid,
            "name": sn.get("name"),
            "signal_type": "neutral",
            "confidence": 0.0,
            "source_expert": "quant",
            "timestamp": _utcnow_z(),
            "evidence": f"scoring unavailable: {exc}",
        }

    experts = score.get("expert_contributions") or {}
    return {
        "subnet_id": netuid,
        "name": sn.get("name"),
        "signal_type": _signal_type(float(score.get("total_score", 50)), hot, sell),
        "confidence": float(score.get("confidence", 0) or 0),
        "source_expert": _source_expert(experts),
        "timestamp": _utcnow_z(),
        "evidence": _evidence(sn, hot, sell, score),
    }


def generate_signals(persist: bool = True) -> Dict[str, Any]:
    subnets = [sn for sn in load_subnets() if (sn.get("netuid") or sn.get("id")) is not None]
    ctx = _market_context()
    signals = [build_signal(sn, ctx) for sn in subnets]
    appended = 0
    if persist:
        appended = SignalStore().append_many(signals)
    return {
        "status": "success",
        "meta": {"count": len(signals), "appended": appended, "generated_at": _utcnow_z()},
        "signals": signals,
    }
