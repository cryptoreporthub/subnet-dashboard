"""Live signal generation for all subnets (Phase L)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.signals.store import EXPERTS, SignalStore

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
PRICE_FLASH_PCT = float(os.environ.get("SIGNAL_PRICE_FLASH_PCT", "15"))


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_subnets() -> List[Dict[str, Any]]:
    try:
        from fetchers.taomarketcap import get_all_subnets

        live = get_all_subnets()
        if live:
            deduped: Dict[Any, Dict[str, Any]] = {}
            for sn in live:
                deduped.setdefault(sn.get("netuid"), sn)
            return list(deduped.values())
    except Exception as exc:
        logger.warning("Live subnet fetch failed for signals: %s", exc)
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [dict(v, netuid=v.get("id", int(k))) for k, v in data.items()]
    except Exception as exc:
        logger.warning("Registry load failed for signals: %s", exc)
        return []


def _market_context() -> Dict[str, Any]:
    try:
        from internal.council.weights import load_weights

        weights = load_weights()
    except Exception:
        weights = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    subnets = _load_subnets()
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


def _derive_signal_type(
    total_score: float,
    hot: Dict[str, Any],
    sell: Dict[str, Any],
) -> str:
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


def _evidence_summary(
    sn: Dict[str, Any],
    hot: Dict[str, Any],
    sell: Dict[str, Any],
    score: Dict[str, Any],
) -> str:
    parts: List[str] = []
    hot_reasons = hot.get("reasons") or []
    sell_reasons = sell.get("reasons") or []
    if hot.get("active") and hot_reasons:
        parts.append("; ".join(hot_reasons[:2]))
    if sell.get("active") and sell_reasons:
        parts.append("; ".join(sell_reasons[:2]))
    tags = score.get("scenario_tags") or {}
    regime = tags.get("regime")
    if regime:
        parts.append(f"regime={regime}")
    chg = sn.get("price_change_24h")
    if chg is not None:
        parts.append(f"24h={float(chg):+.1f}%")
    if not parts:
        parts.append(f"score={score.get('total_score', 0):.1f}")
    return " · ".join(parts)


def _score_subnet(sn: Dict[str, Any], market_context: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    from internal.council.state_vector import (
        _compute_hot_signals,
        _compute_sell_signals,
        _compute_technical_indicators,
        _detect_oversold_convergence,
        score_subnet_for_hour,
    )

    indicators = _compute_technical_indicators(sn)
    convergence = _detect_oversold_convergence(indicators)
    hot = _compute_hot_signals(sn, indicators, convergence)
    sell = _compute_sell_signals(sn, indicators, convergence)
    score = score_subnet_for_hour(sn, market_context)
    return score, hot, sell, indicators


def build_signal_for_subnet(
    sn: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one live signal row for a subnet."""
    market_context = market_context or _market_context()
    netuid = sn.get("netuid") or sn.get("id")
    try:
        score, hot, sell, _ = _score_subnet(sn, market_context)
    except Exception as exc:
        logger.warning("Signal scoring failed for SN%s: %s", netuid, exc)
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
    signal_type = _derive_signal_type(float(score.get("total_score", 50)), hot, sell)
    return {
        "subnet_id": netuid,
        "name": sn.get("name"),
        "signal_type": signal_type,
        "confidence": float(score.get("confidence", 0) or 0),
        "source_expert": _source_expert(experts),
        "timestamp": _utcnow_z(),
        "evidence": _evidence_summary(sn, hot, sell, score),
        "total_score": score.get("total_score"),
        "price_change_24h": sn.get("price_change_24h"),
    }


def generate_live_signals(persist: bool = True) -> Dict[str, Any]:
    """Generate signals for every known subnet and optionally persist changes."""
    subnets = _load_subnets()
    market_context = _market_context()
    signals = [build_signal_for_subnet(sn, market_context) for sn in subnets]
    changed: List[Dict[str, Any]] = []
    if persist:
        store = SignalStore()
        changed = store.append_many(signals)
    return {
        "status": "success",
        "meta": {
            "count": len(signals),
            "changed": len(changed),
            "generated_at": _utcnow_z(),
        },
        "signals": signals,
        "changed_signals": changed,
    }


def price_flash_subnets(threshold_pct: float = PRICE_FLASH_PCT) -> List[Dict[str, Any]]:
    """Subnets with |24h change| above threshold (for alert hooks)."""
    flashes = []
    for sn in _load_subnets():
        try:
            chg = float(sn.get("price_change_24h", 0) or 0)
        except (TypeError, ValueError):
            continue
        if abs(chg) >= threshold_pct:
            flashes.append(
                {
                    "subnet_id": sn.get("netuid") or sn.get("id"),
                    "name": sn.get("name"),
                    "price_change_24h": chg,
                }
            )
    return flashes
