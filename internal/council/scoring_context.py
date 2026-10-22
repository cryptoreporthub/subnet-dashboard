"""Shared market_context enrichment for council scoring (snapshot + hot paths)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def enrich_scoring_market_context(
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hoist Telegram conviction rows + health once per scoring batch.

    Without this, ``calibration_for_subnet`` loads up to 3000 SQLite rows per
    subnet via ``_conviction_rows()`` (Ditto: ~800ms/name on prod-shaped paths).
    """
    ctx = dict(market_context or {})
    if "telegram_conviction_rows" not in ctx:
        try:
            from internal.message_intel.rollup import _conviction_rows

            ctx["telegram_conviction_rows"] = _conviction_rows()
        except Exception:
            ctx["telegram_conviction_rows"] = None
    if "telegram_conviction_index" not in ctx and ctx.get("telegram_conviction_rows") is not None:
        try:
            from internal.message_intel.calibration import index_conviction_calls

            ctx["telegram_conviction_index"] = index_conviction_calls(ctx["telegram_conviction_rows"])
        except Exception:
            ctx["telegram_conviction_index"] = None
    if "telegram_calibration_health" not in ctx and ctx.get("telegram_conviction_rows") is not None:
        try:
            from internal.message_intel.calibration import calibration_health

            ctx["telegram_calibration_health"] = calibration_health(
                conviction_rows=ctx["telegram_conviction_rows"]
            )
        except Exception:
            ctx["telegram_calibration_health"] = None
    if "scenario_memory_scenarios" not in ctx:
        try:
            from internal.council import scenario_memory

            ctx["scenario_memory_scenarios"] = scenario_memory.get_scenarios(limit=300)
        except Exception:
            ctx["scenario_memory_scenarios"] = []
    return ctx
