"""
Technical indicator engine integrated with Mindmap + self-learning loop.

Pipeline:
1. Fetch price candles for subnet tokens.
2. Compute RSI, MACD, and momentum indicators.
3. Detect crossovers and significant events.
4. (Optional) Emit signals into SignalTracker.
5. (Optional) Feed indicator scores into the Selector as a 4th expert.
6. (Optional) Build SimiVision picks and log to Mindmap.
7. (Optional) AdversarialJudge judges indicator predictions.
8. Persist indicator state to disk so /api/indicators can serve it quickly.

The heavy council/selector/simivision/judge phases are disabled by default so
single-worker production deploys don't hang on the first tick. Set
INDICATOR_RUN_COUNCIL_PHASE=true to enable the full feedback loop.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.indicators.crossover_detector import detect_crossovers
from internal.indicators.macd import compute_macd
from internal.indicators.momentum import compute_momentum
from internal.indicators.price_fetcher import fetch_ohlcv
from internal.indicators.rsi import compute_rsi

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")
INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")
RUN_COUNCIL_PHASE = os.environ.get("INDICATOR_RUN_COUNCIL_PHASE", "false").lower() == "true"

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
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)

class IndicatorEngine:
    """Orchestrates technical indicator computation and optional Mindmap integration."""

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
        price_pairs_path: str = PRICE_PAIRS_PATH,
        indicator_state_path: str = INDICATOR_STATE_PATH,
        signal_tracker=None,
        mindmap_bridge=None,
        selector=None,
        judge=None,
        simivision=None,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.price_pairs_path = price_pairs_path
        self.indicator_state_path = indicator_state_path
        self.signal_tracker = signal_tracker
        self.mindmap_bridge = mindmap_bridge
        self.selector = selector
        self.judge = judge
        self.simivision = simivision
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

        # Optional downstream phases. These can be heavy, so we wrap each in
        # its own try/except and let the cycle continue if one fails.
        picks: List[Dict[str, Any]] = []
        if RUN_COUNCIL_PHASE:
            try:
                for event in all_events:
                    self._emit_signal(event)
            except Exception as exc:
                phase_errors.append({"phase": "emit_signals", "error": str(exc)})

            try:
                self._run_selector_with_indicators(per_subnet, registry)
            except Exception as exc:
                phase_errors.append({"phase": "selector", "error": str(exc)})

            try:
                picks = self._build_and_log_picks(per_subnet)
            except Exception as exc:
                phase_errors.append({"phase": "simivision", "error": str(exc)})

            try:
                self._judge_indicator_predictions(per_subnet, registry, all_events)
            except Exception as exc:
                phase_errors.append({"phase": "judge", "error": str(exc)})

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
        """Fetch candles and compute indicators for a single subnet."""
        candles = fetch_ohlcv(str(subnet_id), pairs_path=self.price_pairs_path)
        if len(candles) < 30:
            raise RuntimeError(f"Insufficient candle data for subnet {subnet_id}")

        rsi = compute_rsi(candles)
        macd = compute_macd(candles)
        momentum = compute_momentum(candles)

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
            "events": events,
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

    def _run_selector_with_indicators(
        self, per_subnet: Dict[str, Dict[str, Any]], registry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run the Selector with indicator-enriched context."""
        if self.selector is None:
            from internal.council.selector import Selector
            from internal.council.mindmap_bridge import MindmapBridge
            self.selector = Selector(
                mindmap_bridge=self.mindmap_bridge or MindmapBridge(
                    persistence_path=self.soul_map_path, registry_path=self.registry_path
                )
            )
        context_map: Dict[int, Dict[str, Any]] = {}
        for sid, data in per_subnet.items():
            info = registry.get(sid, {})
            ctx = {
                "emission": info.get("emission", 0.0),
                "social_mentions": info.get("social_mentions", 0),
                "is_overvalued": info.get("is_overvalued", False),
                "indicator_state": {
                    "rsi": data.get("rsi", {}).get("rsi"),
                    "macd_histogram": data.get("macd", {}).get("histogram"),
                    "stochastic_k": data.get("momentum", {}).get("stochastic_k"),
                    "active_signals": [e["event_type"] for e in data.get("events", [])],
                },
            }
            context_map[int(sid)] = ctx

        subnet_ids = list(context_map.keys())
        rotation = self.selector.process_daily_rotation(subnet_ids, context_map)
        if self.mindmap_bridge is None:
            from internal.council.mindmap_bridge import MindmapBridge
            self.mindmap_bridge = MindmapBridge(
                persistence_path=self.soul_map_path, registry_path=self.registry_path
            )
        self.mindmap_bridge.update_soul_map(rotation.get("daily_output", {}))
        return rotation

    def _build_and_log_picks(
        self, per_subnet: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Build SimiVision picks and log them to the Mindmap."""
        if self.simivision is None:
            from internal.council.judge.adversarial import AdversarialJudge
            from internal.simivision.engine import SimiVisionEngine
            judge = self.judge or AdversarialJudge(
                persistence_path=self.soul_map_path,
                registry_path=self.registry_path,
                persist=True,
            )
            self.simivision = SimiVisionEngine(
                registry_path=self.registry_path,
                soul_map_path=self.soul_map_path,
                judge=judge,
            )
        picks = self.simivision.top_signals(n=10)
        if self.mindmap_bridge is None:
            from internal.council.mindmap_bridge import MindmapBridge
            self.mindmap_bridge = MindmapBridge(
                persistence_path=self.soul_map_path, registry_path=self.registry_path
            )
        self.mindmap_bridge.log_simivision_picks(picks)
        return picks

    def _judge_indicator_predictions(
        self,
        per_subnet: Dict[str, Dict[str, Any]],
        registry: Dict[str, Any],
        events: List[Dict[str, Any]],
    ) -> None:
        """Judge indicator-based predictions and feed back into the learning loop."""
        if self.judge is None or self.mindmap_bridge is None:
            from internal.council.judge.adversarial import AdversarialJudge
            from internal.council.mindmap_bridge import MindmapBridge
            self.judge = self.judge or AdversarialJudge(
                persistence_path=self.soul_map_path,
                registry_path=self.registry_path,
                persist=True,
            )
            self.mindmap_bridge = self.mindmap_bridge or MindmapBridge(
                persistence_path=self.soul_map_path, registry_path=self.registry_path
            )
        for sid, data in per_subnet.items():
            info = registry.get(sid, {})
            active = [e["event_type"] for e in data.get("events", [])]
            if not active:
                continue

            bullish = any(
                e in active for e in ("rsi_oversold_reversal", "macd_bullish_cross", "stochastic_oversold_reversal")
            )
            bearish = any(
                e in active for e in ("rsi_overbought_reversal", "macd_bearish_cross")
            )
            predicted_direction = "bullish" if bullish else "bearish" if bearish else "neutral"

            decision = {
                "subnet_id": int(sid),
                "recommended_action": "accumulate" if bullish else "reduce" if bearish else "hold",
                "consensus_score": 0.75 if bullish else 0.25 if bearish else 0.5,
                "expert_breakdown": {
                    "technical": {
                        "score": 0.8 if bullish else 0.2 if bearish else 0.5,
                        "signals": active,
                    }
                },
                "indicator_context": {
                    "signals_present": active,
                    "predicted_direction": predicted_direction,
                    "signal_count": len(active),
                },
            }

            outcome = {
                "status": info.get("status", "unknown"),
                "emission": info.get("emission", 0.0),
                "social_mentions": info.get("social_mentions", 0),
                "is_overvalued": info.get("is_overvalued", False),
            }

            verdict = self.judge.judge_outcome_only(int(sid), decision, outcome)

            outcome_val = 1 if verdict.get("outcome_label") == "validated" else -1 if verdict.get("outcome_label") == "contradicted" else 0
            note = f"Indicator prediction ({predicted_direction}) judged {verdict.get('outcome_label')} for signals: {', '.join(active)}"
            self.mindmap_bridge.log_simivision_feedback(int(sid), outcome_val, note)
            self._persist_indicator_verdict(int(sid), decision, verdict)

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
        """Persist indicator state to a dedicated file and inside the soul map."""
        _save_json(self.indicator_state_path, indicator_state)
        try:
            soul_map = _load_json(self.soul_map_path)
            soul_map.setdefault("soul_map_state", {})["indicator_last_state"] = indicator_state
            _save_json(self.soul_map_path, soul_map)
        except Exception:
            pass

    def _persist_indicator_verdict(
        self, subnet_id: int, decision: Dict[str, Any], verdict: Dict[str, Any]
    ) -> None:
        """Persist a per-subnet indicator-context verdict inside the soul map."""
        try:
            soul_map = _load_json(self.soul_map_path)
            soul_map.setdefault("soul_map_state", {}).setdefault("indicator_verdicts", {})[str(subnet_id)] = {
                "decision": decision,
                "verdict": verdict,
                "persisted_at": _now_iso(),
            }
            _save_json(self.soul_map_path, soul_map)
        except Exception:
            pass
