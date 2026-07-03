"""
Technical indicator engine.

Pipeline:
1. Fetch price candles for subnet tokens.
2. Compute RSI, MACD, and momentum indicators.
3. Detect crossovers and significant events.
4. (Optional) Emit signals into SignalTracker.
5. Persist indicator state to disk so /api/indicators can serve it quickly.

The legacy council/selector/simivision/judge phases have been removed as part
of the Council hygiene pass; only the signal-emission phase remains optional.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.indicators.bollinger import compute_bollinger
from internal.indicators.cci import compute_cci
from internal.indicators.crossover_detector import detect_crossovers
from internal.indicators.keltner import compute_keltner
from internal.indicators.macd import compute_macd
from internal.indicators.mfi import compute_mfi
from internal.indicators.momentum import compute_momentum
from internal.indicators.price_fetcher import fetch_ohlcv
from internal.indicators.rsi import compute_rsi

logger = logging.getLogger(__name__)

# Ensure the data directory exists at module load time.
os.makedirs('data', exist_ok=True)

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")
INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")
RUN_SIGNAL_PHASE = os.environ.get("INDICATOR_RUN_SIGNAL_PHASE", "false").lower() == "true"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

class IndicatorEngine:
    """Orchestrates technical indicator computation and optional Mindmap integration."""

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
        price_pairs_path: str = PRICE_PAIRS_PATH,
        indicator_state_path: str = INDICATOR_STATE_PATH,
        signal_tracker=None,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.price_pairs_path = price_pairs_path
        self.indicator_state_path = indicator_state_path
        self.signal_tracker = signal_tracker
        self._last_per_subnet: Dict[str, Dict[str, Any]] = {}

    def run_cycle(self, subnet_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """Run the indicator pipeline for the given subnets."""
        run_at = _now_iso()
        registry = _load_json(self.registry_path)
        if subnet_ids is None:
            subnet_ids = [int(k) for k in registry.keys() if k.isdigit()]

        per_subnet: Dict[str, Dict[str, Any]] = {}
        all_events: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        phase_errors: List[Dict[str, Any]] = []

        for sid in subnet_ids:
            try:
                result = self._process_subnet(sid, registry.get(str(sid), {}))
                per_subnet[str(sid)] = result
                all_events.extend(result.get("events", []))
            except Exception as exc:
                errors.append({"subnet_id": sid, "error": str(exc)})

        # Optional signal-emission phase.
        picks: List[Dict[str, Any]] = []
        if RUN_SIGNAL_PHASE:
            try:
                for event in all_events:
                    self._emit_signal(event)
            except Exception as exc:
                phase_errors.append({"phase": "emit_signals", "error": str(exc)})

        # Always persist indicator state so /api/indicators can serve data.
        indicator_state = {
            "run_at": run_at,
            "last_run_at": run_at,
            "signals_emitted": len(all_events),
            "subnets_processed": len(per_subnet),
            "errors": errors,
            "phase_errors": phase_errors,
            "per_subnet": {
                sid: {
                    "rsi": data.get("rsi", {}).get("rsi"),
                    "macd_histogram": data.get("macd", {}).get("histogram"),
                    "stochastic_k": data.get("momentum", {}).get("stochastic_k"),
                    "active_signals": [e["event_type"] for e in data.get("events", [])],
                    "last_updated": run_at,
                }
                for sid, data in per_subnet.items()
            },
        }
        self._persist_indicator_state(indicator_state)
        self._last_per_subnet = per_subnet

        return {
            "ok": True,
            "run_at": run_at,
            "subnets_processed": len(per_subnet),
            "signals_emitted": len(all_events),
            "errors": errors,
            "phase_errors": phase_errors,
            "per_subnet": per_subnet,
            "events": all_events,
            "picks": picks,
        }

    def _process_subnet(self, subnet_id: int, registry_item: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch candles and compute all 8 oscillators for a single subnet."""
        candles = fetch_ohlcv(str(subnet_id), pairs_path=self.price_pairs_path)
        if len(candles) < 30:
            raise RuntimeError(f"Insufficient candle data for subnet {subnet_id}")

        # Feed the latest candle into the Pump Cycle Tracker (v2) so the
        # CUSUM evidence accumulator + 6-phase model stay in sync with every
        # scheduler tick. Defensive: a tracker failure must never break the
        # indicator pipeline.
        try:
            from datastore.pump_tracker import get_pump_tracker
            last = candles[-1]
            name = registry_item.get("name") if isinstance(registry_item, dict) else None
            get_pump_tracker().on_tick(
                netuid=subnet_id,
                name=name,
                price=float(last.get("close", 0.0) or 0.0),
                volume=float(last.get("volume", 0.0) or 0.0),
                timestamp=last.get("timestamp"),
            )
        except Exception as exc:
            logger.warning("pump_tracker hook in indicator engine failed: %s", exc)

        # Compute all 8 oscillators
        rsi = compute_rsi(candles)
        macd = compute_macd(candles)
        momentum = compute_momentum(candles)
        bollinger = compute_bollinger(candles)
        mfi = compute_mfi(candles)
        cci = compute_cci(candles)
        keltner = compute_keltner(candles)

        prev = self._last_per_subnet.get(str(subnet_id), {})
        prev_rsi = prev.get("rsi")
        prev_macd = prev.get("macd")
        prev_momentum = prev.get("momentum")

        events = detect_crossovers(
            rsi,
            macd,
            momentum,
            prev_rsi=prev_rsi,
            prev_macd=prev_macd,
            prev_momentum=prev_momentum,
            timestamp=_now_iso(),
        )

        return {
            "candles_count": len(candles),
            "rsi": rsi,
            "macd": macd,
            "momentum": momentum,
            "bollinger": bollinger,
            "mfi": mfi,
            "cci": cci,
            "keltner": keltner,
            "events": events,
            "oscillators_computed": 7,
        }

    def _emit_signal(self, event: Dict[str, Any]) -> None:
        """Record a crossover event as a SignalTracker signal."""
        if self.signal_tracker is None:
            from internal.signals.signal_tracker import SignalTracker
            self.signal_tracker = SignalTracker()
        metadata = {
            "signal_type": event.get("signal_type"),
            "direction": event.get("direction"),
            "strength": event.get("strength"),
            "indicator_value": event.get("indicator_value"),
            "threshold": event.get("threshold"),
            "description": event.get("description"),
        }
        self.signal_tracker.record_signal(
            asset="INDICATOR",
            source="indicator",
            timestamp=event.get("timestamp"),
            metadata=metadata,
        )

    def get_indicator_state(self) -> Dict[str, Any]:
        """Return the most recently persisted indicator state."""
        state = _load_json(self.indicator_state_path)
        if state:
            return state
        # Fallback to the copy stored inside the soul map by older runs.
        try:
            soul_map = _load_json(self.soul_map_path)
            return soul_map.get("soul_map_state", {}).get("indicator_last_state", {})
        except Exception:
            return {}

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Return active crossover alerts from the persisted indicator state."""
        state = self.get_indicator_state()
        alerts: List[Dict[str, Any]] = []
        for sid, data in state.get("per_subnet", {}).items():
            for event_type in data.get("active_signals", []):
                alerts.append({"subnet_id": int(sid), "event_type": event_type})
        return alerts

    def _persist_indicator_state(self, indicator_state: Dict[str, Any]) -> None:
        """Persist indicator state to a dedicated file."""
        _save_json(self.indicator_state_path, indicator_state)
