"""Phase H-full premium dashboard context builders (Agent A).

Variable shapes: docs/premium-dashboard-redesign.md §§2–6, §10.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _subnet_bundle(sn: Dict[str, Any], market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from internal.council.state_vector import (
        _compute_hot_signals,
        _compute_sell_signals,
        _compute_signal_impact,
        _compute_technical_indicators,
        _detect_overbought_convergence,
        _detect_oversold_convergence,
        _get_price_history,
        score_subnet_for_hour,
    )

    indicators = _compute_technical_indicators(sn)
    oversold = _detect_oversold_convergence(indicators)
    overbought = _detect_overbought_convergence(indicators)
    hot = _compute_hot_signals(sn, indicators, oversold)
    sell = _compute_sell_signals(sn, indicators, overbought)
    signal_impact = _compute_signal_impact(sn, indicators, hot, sell)
    score = score_subnet_for_hour(sn, market_context)
    history = _get_price_history(sn.get("netuid"), sn)
    closes = history.get("closes") or []
    sparkline = [round(float(c), 6) for c in closes[-12:]] if closes else []

    return {
        "indicators": indicators,
        "oversold": oversold,
        "overbought": overbought,
        "hot": hot,
        "sell": sell,
        "signal_impact": signal_impact,
        "score": score,
        "sparkline": sparkline,
    }


def _apply_sell_over_hot(hot: Dict[str, Any], sell: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    hot_out = dict(hot)
    sell_out = dict(sell)
    if sell_out.get("active"):
        hot_out["active"] = False
        hot_out["label"] = None
        hot_out["suppressed_by"] = "SELL ALERT"
    return hot_out, sell_out


def _recommendation(
    rsi_signal: str,
    conviction: float,
    sell_active: bool,
) -> str:
    if sell_active or rsi_signal == "overbought":
        return "SELL"
    if rsi_signal == "oversold":
        return "BUY"
    if conviction < 40:
        return "WATCH"
    return "HOLD"


def _pick_reasons(bundle: Dict[str, Any], limit: int = 3) -> List[str]:
    reasons: List[str] = []
    sell = bundle.get("sell") or {}
    hot = bundle.get("hot") or {}
    if sell.get("active"):
        reasons.extend(list(sell.get("reasons") or [])[:limit])
    elif hot.get("active"):
        reasons.extend(list(hot.get("reasons") or [])[:limit])
    score = bundle.get("score") or {}
    tags = score.get("scenario_tags") or {}
    if isinstance(tags, dict):
        for key, val in tags.items():
            if val and len(reasons) < limit:
                reasons.append(f"{key}: {val}")
    chg = _float((bundle.get("_sn") or {}).get("price_change_24h"))
    if len(reasons) < limit and abs(chg) >= 2:
        reasons.append(f"24h move {chg:+.1f}%")
    return reasons[:limit] or ["Composite conviction from council scoring"]


def _prediction_stub(sn: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    impact = bundle.get("signal_impact") or {}
    net_pct = _float(impact.get("net_predicted_pct"))
    direction = "up" if net_pct >= 0 else "down"
    horizon = 4
    mag = abs(net_pct) if net_pct else 1.0
    sign = "+" if direction == "up" else "-"
    return {
        "netuid": sn.get("netuid"),
        "name": sn.get("name"),
        "direction": direction,
        "predicted_pct": round(net_pct, 2),
        "horizon_hours": horizon,
        "status": "pending",
        "statement": f"predicted to move {sign}{mag:.1f}% within {horizon} hours",
    }


def build_simivision_picks(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Top 6 SimiVision picks with conviction, hot/sell, SELL>HOT enforced."""
    ranked: List[tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for sn in subnets:
        if not isinstance(sn, dict) or sn.get("netuid") is None:
            continue
        bundle = _subnet_bundle(sn, market_context)
        bundle["_sn"] = sn
        total = _float((bundle.get("score") or {}).get("total_score"))
        ranked.append((total, sn, bundle))
    ranked.sort(key=lambda row: row[0], reverse=True)

    picks: List[Dict[str, Any]] = []
    for rank, (total, sn, bundle) in enumerate(ranked[:6], start=1):
        hot, sell = _apply_sell_over_hot(bundle["hot"], bundle["sell"])
        conviction = min(95, max(0, round(total * 0.95)))
        rsi = bundle["indicators"].get("rsi") or {}
        rsi_signal = rsi.get("signal", "neutral") if isinstance(rsi, dict) else "neutral"
        recommendation = _recommendation(rsi_signal, conviction, bool(sell.get("active")))
        picks.append(
            {
                "rank": rank,
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "emission": _float(sn.get("emission")),
                "apy": _float(sn.get("apy")),
                "price": _float(sn.get("price")),
                "price_change_24h": _float(sn.get("price_change_24h")),
                "conviction": conviction,
                "recommendation": recommendation,
                "reasons": _pick_reasons(bundle),
                "sparkline": bundle["sparkline"],
                "hot": hot,
                "sell": sell,
                "prediction": _prediction_stub(sn, bundle),
                "signal_impact": bundle["signal_impact"],
            }
        )
    return picks


def build_undervalued_radar(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Top 8 subnets by undervalued_score."""
    if not subnets:
        return []

    emissions = [_float(s.get("emission")) for s in subnets if _float(s.get("emission")) > 0]
    volumes = [_float(s.get("volume")) for s in subnets if _float(s.get("volume")) > 0]
    median_emission = sorted(emissions)[len(emissions) // 2] if emissions else 1.0
    median_volume = sorted(volumes)[len(volumes) // 2] if volumes else 1.0

    scored: List[tuple[float, Dict[str, Any], List[str]]] = []
    for sn in subnets:
        if not isinstance(sn, dict):
            continue
        price = _float(sn.get("price"))
        emission = _float(sn.get("emission"))
        apy = _float(sn.get("apy"))
        volume = _float(sn.get("volume"))
        if price <= 0 or emission <= 0:
            continue
        pe_ratio = price / emission
        low_pe = max(0.0, 1.0 - min(pe_ratio / 10.0, 1.0))
        apy_score = min(apy / 50.0, 1.0)
        vol_score = max(0.0, 1.0 - (volume / max(median_volume, 1.0)))
        undervalued_score = round((low_pe * 0.45 + apy_score * 0.35 + vol_score * 0.20) * 100, 2)
        reasons: List[str] = []
        if pe_ratio < median_emission / max(median_emission, 0.01):
            reasons.append(f"Low price/emission ({pe_ratio:.2f})")
        if apy >= 20:
            reasons.append(f"Strong APY ({apy:.1f}%)")
        if volume < median_volume:
            reasons.append("Volume below peer median")
        scored.append((undervalued_score, sn, reasons[:3]))

    scored.sort(key=lambda row: row[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for rank, (score, sn, reasons) in enumerate(scored[:8], start=1):
        out.append(
            {
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "undervalued_score": score,
                "rank": rank,
                "emission": _float(sn.get("emission")),
                "apy": _float(sn.get("apy")),
                "price": _float(sn.get("price")),
                "price_change_24h": _float(sn.get("price_change_24h")),
                "volume": _float(sn.get("volume")),
                "reasons": reasons or ["Composite undervaluation score"],
            }
        )
    return out


def _indicator_panel(indicators: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("rsi", "stochastic", "bollinger", "mfi", "cci", "williams_r", "keltner", "macd", "ma_cross")
    panel: Dict[str, Any] = {}
    for key in keys:
        val = indicators.get(key)
        if isinstance(val, dict):
            panel[key] = val
    panel["history_source"] = indicators.get("history_source", "synthetic")
    panel["history_length"] = indicators.get("history_length", 0)
    return panel


def build_technical_indicators(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Per-subnet indicator panel for top 20 subnets by emission."""
    ranked = sorted(
        [s for s in subnets if isinstance(s, dict)],
        key=lambda s: _float(s.get("emission")),
        reverse=True,
    )[:20]
    rows: List[Dict[str, Any]] = []
    for sn in ranked:
        bundle = _subnet_bundle(sn, market_context)
        hot, sell = _apply_sell_over_hot(bundle["hot"], bundle["sell"])
        rows.append(
            {
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "indicators": _indicator_panel(bundle["indicators"]),
                "convergence": {
                    "oversold": bundle["oversold"],
                    "overbought": bundle["overbought"],
                },
                "hot": hot,
                "sell": sell,
            }
        )
    return rows


def build_signal_impact(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    *,
    predictions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Per-subnet signal impact; prioritize subnets with active predictions or strong signals."""
    pred_netuids = {
        p.get("netuid") for p in (predictions or []) if isinstance(p, dict) and p.get("netuid") is not None
    }
    rows: List[tuple[float, Dict[str, Any]]] = []
    for sn in subnets:
        if not isinstance(sn, dict):
            continue
        bundle = _subnet_bundle(sn, market_context)
        impact = dict(bundle["signal_impact"])
        priority = abs(_float(impact.get("net_predicted_pct")))
        if sn.get("netuid") in pred_netuids:
            priority += 5.0
        if impact.get("hot_active") or impact.get("sell_active"):
            priority += 3.0
        row = {
            "netuid": sn.get("netuid"),
            "name": sn.get("name"),
            **impact,
        }
        rows.append((priority, row))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in rows[:24]]


def build_social_sentiment(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-subnet social sentiment; honest-empty when message_intel unavailable."""
    try:
        from internal.message_intel.store import get_db

        db = get_db()
        if db is None:
            return []
        rows: List[Dict[str, Any]] = []
        for sn in subnets[:40]:
            if not isinstance(sn, dict):
                continue
            netuid = sn.get("netuid")
            name = sn.get("name")
            try:
                stats = db.netuid_stats(int(netuid)) if netuid is not None else None
            except Exception:
                stats = None
            if not stats:
                continue
            score = _float(stats.get("avg_sentiment", stats.get("score")))
            label = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"
            rows.append(
                {
                    "netuid": netuid,
                    "name": name,
                    "score": round(score, 3),
                    "label": label,
                    "mentions": int(stats.get("mention_count", stats.get("mentions", 0)) or 0),
                    "feed": [],
                }
            )
        return rows
    except Exception as exc:
        logger.debug("social_sentiment fallback empty: %s", exc)
        return []


def build_h_full_dashboard_keys(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    predictions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """All seven H-full template keys in one dict."""
    from internal.analytics.root_context import build_market_intelligence, build_staking_analytics

    return {
        "simivision_picks": build_simivision_picks(subnets, market_context),
        "undervalued_radar": build_undervalued_radar(subnets),
        "technical_indicators": build_technical_indicators(subnets, market_context),
        "signal_impact": build_signal_impact(subnets, market_context, predictions=predictions),
        "social_sentiment": build_social_sentiment(subnets),
        "market_intelligence": build_market_intelligence(subnets),
        "staking_analytics": build_staking_analytics(subnets),
    }
