"""
Technical indicator engine integrated with Mindmap + self-learning loop.

Pipeline:
1. Fetch price candles for subnet tokens.
2. Compute RSI, MACD, and momentum indicators.
3. Detect crossovers and significant events.
4. Emit signals into SignalTracker.
5. Feed indicator scores into the Selector as a 4th expert (TechnicalExpert).
6. Log indicator signals to MindmapBridge (soul_map state).
7. AdversarialJudge judges indicator predictions against price outcomes.
8. SimiVision picks include indicator conviction in scoring.
9. Learning loop: judge verdicts update indicator signal weight over time.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.judge.adversarial import AdversarialJudge
from internal.council.mindmap_bridge import MindmapBridge
from internal.council.selector import Selector
from internal.indicators.crossover_detector import detect_crossovers
from internal.indicators.macd import compute_macd
from internal.indicators.momentum import compute_momentum
from internal.indicators.price_fetcher import fetch_ohlcv
from internal.indicators.rsi import compute_rsi
from internal.signals.signal_tracker import SignalTracker
from internal.simivision.engine import SimiVisionEngine

REGISTRY_PATH = os.environ.get("REGISTRY_PATH", "config/registry.json")
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
PRICE_PAIRS_PATH = os.environ.get("PRICE_PAIRS_PATH", "config/price_pairs.json")


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
    """Orchestrates technical indicator computation and Mindmap integration."""

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        soul_map_path: str = SOUL_MAP_PATH,
        price_pairs_path: str = PRICE_PAIRS_PATH,
        signal_tracker: Optional[SignalTracker] = None,
        mindmap_bridge: Optional[MindmapBridge] = None,
        selector: Optional[Selector] = None,
        judge: Optional[AdversarialJudge] = None,
        simivision: Optional[SimiVisionEngine] = None,
    ):
        self.registry_path = registry_path
        self.soul_map_path = soul_map_path
        self.price_pairs_path = price_pairs_path
        self.signal_tracker = signal_tracker or SignalTracker()
        self.mindmap_bridge = mindmap_bridge or MindmapBridge(
            persistence_path=soul_map_path, registry_path=registry_path
        )
        self.selector = selector or Selector(mindmap_bridge=self.mindmap_bridge)
        self.judge = judge or AdversarialJudge(
            persistence_path=soul_map_path,
            registry_path=registry_path,
            persist=True,
        )
        self.simivision = simivision or SimiVisionEngine(
            registry_path=registry_path, soul_map_path=soul_map_path, judge=self.judge
        )
        self._last_per_subnet: Dict[str, Dict[str, Any]] = {}

    def run_cycle(self, subnet_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """Run the full indicator pipeline for the given subnets."""
        run_at = _now_iso()
        registry = _load_json(self.registry_path)
        if subnet_ids is None:
            subnet_ids = [int(k) for k in registry.keys() if k.isdigit()]

        per_subnet: Dict[str, Dict[str, Any]] = {}
        all_events: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for sid in subnet_ids:
            try:
                result = self._process_subnet(sid, registry.get(str(sid), {}))
                per_subnet[str(sid)] = result
                all_events.extend(result.get("events", []))
            except Exception as exc:
                errors.append({"subnet_id": sid, "error": str(exc)})

        # Emit all detected crossover events as structured signals.
        for event in all_events:
            self._emit_signal(event)

        # Run selector with enriched context so TechnicalExpert can contribute.
        self._run_selector_with_indicators(per_subnet, registry)

        # Build SimiVision picks with indicator conviction and log to Mindmap.
        picks = self._build_and_log_picks(per_subnet)

        # Judge indicator predictions and log feedback to the learning loop.
        self._judge_indicator_predictions(per_subnet, registry, all_events)

        # Persist indicator state to soul_map.
        indicator_state = {
            "last_run_at": run_at,
            "signals_emitted": len(all_events),
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
            "per_subnet": per_subnet,
            "events": all_events,
            "picks": picks,
        }

    def _process_subnet(self, subnet_id: int, registry_item: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch candles and compute indicators for a single subnet."""
        candles = fetch_ohlcv(str(subnet_id))
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
        metadata = {
            "signal_type": event.get("signal_type"),
            "direction": event.get("direction"),
            "strength": event.get("strength"),
            "indicator_value": event.get("indicator_value"),
            "threshold": event.get("threshold"),
            "description": event.get("description"),
        }
        # Asset is generic; we use the indicator taxonomy asset tag.
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
        self.mindmap_bridge.update_soul_map(rotation.get("daily_output", {}))
        return rotation

    def _build_and_log_picks(
        self, per_subnet: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Build SimiVision picks and log them to the Mindmap."""
        picks = self.simivision.top_signals(n=10)
        self.mindmap_bridge.log_simivision_picks(picks)
        return picks

    def _judge_indicator_predictions(
        self,
        per_subnet: Dict[str, Dict[str, Any]],
        registry: Dict[str, Any],
        events: List[Dict[str, Any]],
    ) -> None:
        """Judge indicator-based predictions and feed back into the learning loop."""
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

            # Log feedback to the Mindmap self-learning loop.
            outcome_val = 1 if verdict.get("outcome_label") == "validated" else -1 if verdict.get("outcome_label") == "contradicted" else 0
            note = f"Indicator prediction ({predicted_direction}) judged {verdict.get('outcome_label')} for signals: {', '.join(active)}"
            self.mindmap_bridge.log_simivision_feedback(int(sid), outcome_val, note)

            # Persist the indicator-context linkage in the soul_map.
            self._persist_indicator_verdict(int(sid), decision, verdict)

    def _persist_indicator_state(self, indicator_state: Dict[str, Any]) -> None:
        soul_map = _load_json(self.soul_map_path)
        soul_map.setdefault("soul_map_state", {})["indicator_state"] = indicator_state
        soul_map["soul_map_state"]["updated_at"] = _now_iso()
        _save_json(self.soul_map_path, soul_map)

    def _persist_indicator_verdict(
        self, subnet_id: int, decision: Dict[str, Any], verdict: Dict[str, Any]
    ) -> None:
        soul_map = _load_json(self.soul_map_path)
        trail = soul_map.setdefault("indicator_learning_trail", [])
        trail.append(
            {
                "subnet_id": subnet_id,
                "timestamp": _now_iso(),
                "indicator_context": decision.get("indicator_context"),
                "verdict": {
                    "score": verdict.get("score"),
                    "confidence": verdict.get("confidence"),
                    "outcome_label": verdict.get("outcome_label"),
                    "note": verdict.get("note"),
                },
            }
        )
        trail = trail[-200:]
        soul_map["indicator_learning_trail"] = trail
        _save_json(self.soul_map_path, soul_map)

    def get_indicator_state(self) -> Dict[str, Any]:
        """Return the latest persisted indicator state from the soul map."""
        soul_map = _load_json(self.soul_map_path)
        return soul_map.get("soul_map_state", {}).get("indicator_state", {})

    def get_alerts(self) -> List[Dict[str, Any]]:
        """Return active crossover alerts from the last cycle."""
        alerts = []
        state = self.get_indicator_state()
        for sid, data in state.get("per_subnet", {}).items():
            for signal in data.get("active_signals", []):
                alerts.append({"subnet_id": sid, "event_type": signal, "last_updated": data.get("last_updated")})
        return alerts

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Alias for get_alerts used by the API."""
        return self.get_alerts()
