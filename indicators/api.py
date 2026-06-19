"""
Flask Blueprint exposing the technical indicator layer via /api/indicators.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from indicators.indicator_engine import IndicatorEngine
from indicators.indicator_scheduler import get_indicator_scheduler_state
from internal.freshness import indicator_freshness, overall_freshness

bp = Blueprint("indicators_api", __name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state(path: str = "data/indicator_state.json") -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


@bp.route("/", methods=["GET"])
def indicator_summary():
    """Return the full indicator-layer summary for all configured pairs."""
    engine = IndicatorEngine()
    state = engine.get_state()
    return jsonify(
        {
            "status": "success",
            "updated_at": state.get("updated_at"),
            "freshness": indicator_freshness(),
            "scheduler": get_indicator_scheduler_state(),
            "signals": state.get("signals", []),
        }
    )


@bp.route("/<pair>", methods=["GET"])
def indicator_pair(pair: str):
    """Return detailed indicators for a single pair (e.g. TAO-USD)."""
    engine = IndicatorEngine()
    record = engine.get_pair(pair.upper())
    if not record:
        return jsonify({"status": "error", "message": f"Pair {pair} not found"}), 404
    return jsonify(
        {
            "status": "success",
            "pair": pair.upper(),
            "data": record,
            "freshness": indicator_freshness(),
        }
    )


@bp.route("/signals", methods=["GET"])
def indicator_signals():
    """Return recent indicator signals, optionally filtered by signal_type."""
    state = _load_state()
    signal_type = request.args.get("signal_type")
    signals = state.get("signals", [])
    if signal_type:
        signals = [s for s in signals if s.get("signal_type") == signal_type.lower()]
    return jsonify(
        {
            "status": "success",
            "updated_at": state.get("updated_at"),
            "count": len(signals),
            "signals": signals,
        }
    )


@bp.route("/backtest/<pair>", methods=["GET"])
def indicator_backtest(pair: str):
    """Return raw price + indicator data for ad-hoc backtesting / charting."""
    engine = IndicatorEngine()
    return jsonify(
        {
            "status": "success",
            "pair": pair.upper(),
            "data": engine.backtest_data(pair.upper()),
        }
    )


@bp.route("/health", methods=["GET"])
def indicator_health():
    """Health check for the indicator layer."""
    return jsonify(
        {
            "status": "ok",
            "layer": "indicators",
            "checked_at": _now_iso(),
            "freshness": indicator_freshness(),
        }
    )
