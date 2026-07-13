"""TAO Signal Hub cycle runner."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.signal_hub.anomaly import (
    TRACKER_IDS,
    evaluate_subnet_anomalies,
    evaluate_tao_breadth,
    threshold_snapshot,
)
from internal.signal_hub.l_bridge import publish_to_phase_l
from internal.signal_hub.overlay import build_hub_overlay
from internal.signal_hub.state import load_hub_state, save_hub_state

logger = logging.getLogger(__name__)

PRICE_CACHE_PATH = os.environ.get("PRICE_CACHE_PATH", "data/price_cache.json")
SOCIAL_CONVICTION = float(os.environ.get("HUB_SOCIAL_CONVICTION", "70"))


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_price_cache() -> Dict[str, Any]:
    try:
        with open(PRICE_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _population_changes(subnets: List[Dict[str, Any]]) -> List[float]:
    out: List[float] = []
    for sn in subnets:
        try:
            out.append(float(sn.get("price_change_24h", 0) or 0))
        except (TypeError, ValueError):
            continue
    return out


def _social_shift_hits() -> List[Dict[str, Any]]:
    try:
        from internal.message_intel.engine import live_stats

        stats = live_stats()
        if int(stats.get("total_messages", 0) or 0) <= 0:
            return []
    except Exception:
        return []

    try:
        from internal.message_intel.engine import list_messages

        rows = list_messages(limit=20).get("messages") or []
    except Exception:
        return []

    hits: List[Dict[str, Any]] = []
    for row in rows:
        verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
        try:
            conviction = float(verdict.get("conviction") or 0)
        except (TypeError, ValueError):
            conviction = 0.0
        if conviction < SOCIAL_CONVICTION:
            continue
        netuid = row.get("netuid")
        if netuid is None:
            continue
        label = str(verdict.get("verdict") or "neutral")
        hits.append(
            {
                "type": "social_shift",
                "subnet_id": netuid,
                "name": row.get("subnet_name"),
                "conviction": conviction,
                "direction": "bearish" if label == "bearish" else "bullish" if label == "bullish" else "neutral",
                "severity": "warning",
            }
        )
    return hits


class HubTracker:
    """Chart-led monitor: subnets → anomaly guards → Phase L + overlay cache."""

    def run_cycle(self, *, persist: bool = True) -> Dict[str, Any]:
        from internal.signals.pipeline import load_subnets

        subnets = load_subnets()
        cache = _load_price_cache()
        population = _population_changes(subnets)
        anomalies: List[Dict[str, Any]] = []

        for sn in subnets:
            anomalies.extend(
                evaluate_subnet_anomalies(sn, cache=cache, population_changes=population)
            )

        breadth = evaluate_tao_breadth(population)
        if breadth:
            anomalies.append(breadth)

        anomalies.extend(_social_shift_hits())

        publish_result = publish_to_phase_l(anomalies, persist_signals=persist) if persist else {
            "signals_written": 0,
            "alerts_created": 0,
            "signals": [],
        }
        if not persist:
            from internal.signal_hub.l_bridge import hub_signals_to_store_rows

            publish_result["signals"] = hub_signals_to_store_rows(anomalies)

        overlay = build_hub_overlay([a for a in anomalies if a.get("subnet_id") is not None])
        overlay_json = {str(k): v for k, v in overlay.items()}

        state_patch = {
            "active": True,
            "last_cycle_at": _utcnow_z(),
            "trackers": list(TRACKER_IDS),
            "anomalies": anomalies,
            "last_signals": publish_result.get("signals") or [],
            "overlay": overlay_json,
            "meta": {
                "anomaly_count": len(anomalies),
                "signals_emitted": len(publish_result.get("signals") or []),
                "signals_written": publish_result.get("signals_written", 0),
                "alerts_created": publish_result.get("alerts_created", 0),
                "subnet_count": len(subnets),
            },
        }
        if persist:
            save_hub_state(state_patch)

        return {
            "status": "ok",
            "cycle_at": state_patch["last_cycle_at"],
            "anomalies": anomalies,
            "overlay": overlay,
            "publish": publish_result,
            "meta": state_patch["meta"],
        }


def run_hub_cycle(*, persist: bool = True) -> Dict[str, Any]:
    return HubTracker().run_cycle(persist=persist)


def hub_status(*, refresh: bool = False) -> Dict[str, Any]:
    if refresh:
        run_hub_cycle(persist=True)
    state = load_hub_state()
    auto = os.environ.get("SIGNAL_HUB_AUTO", "").lower() in {"1", "true", "on", "yes"}
    return {
        "status": "ok",
        "hub": {
            "active": bool(state.get("active")),
            "last_cycle_at": state.get("last_cycle_at"),
            "trackers": state.get("trackers") or list(TRACKER_IDS),
            "anomaly_count": len(state.get("anomalies") or []),
            "signals_emitted": len(state.get("last_signals") or []),
            "scheduler": {"auto": auto},
            "meta": state.get("meta") or {},
        },
        "thresholds": threshold_snapshot(),
    }


def hub_signals_list() -> Dict[str, Any]:
    state = load_hub_state()
    signals = list(state.get("last_signals") or [])
    return {
        "status": "ok",
        "signals": signals,
        "meta": {"count": len(signals), "source": "signal_hub"},
    }
