"""
Pump Cycle Tracker v2 — CUSUM-based evidence accumulation with 6-phase model.

Based on research from:
- CUSUM change-point detection (Page 1954, academic pump cycle detection)
- Wyckoff market cycle phases (Accumulation -> Markup -> Distribution -> Decline)
- Parabolic Move Detector (ATR-normalized acceleration detection)
- TradeZella-style outcome tracking and behavioral profiling

Phases:
  ACCUMULATION    — price flat, evidence near 0, volume declining
  MARKUP          — CUSUM evidence rising, price accelerating (pump)
  PARABOLIC       — extreme acceleration (ATR/bar > 2.0)
  DISTRIBUTION    — price near peak, evidence plateauing
  DECLINE         — evidence falling, price declining
  RE_ACCUMULATION — flat after decline, preparing for next cycle

Detection uses standardized z-returns + Page CUSUM accumulator:
  z_t = (r_t - rolling_mean) / rolling_std   (lookback=20)
  C_t = max(0, C_{t-1} + z_t - k)            (k=0.5)
  Pump detected when C_t > rolling 95th percentile threshold

This is adaptive across assets and causal (no future leakage).
"""

import json
import logging
import math
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

STATE_PATH = os.environ.get("PUMP_CYCLES_PATH", "data/pump_cycles.json")

LOOKBACK = 20          # rolling window for z-return standardization
CUSUM_K = 0.5         # CUSUM drift allowance
PARABOLIC_ATR = 2.0   # ATRs-per-bar above which a move is "parabolic"
MAX_SNAPSHOTS = 600   # per-subnet rolling price history kept in memory
PRONENESS_TICKS = 5   # run heavy proneness/prediction computations every Nth tick

PHASES = (
    "ACCUMULATION",
    "MARKUP",
    "PARABOLIC",
    "DISTRIBUTION",
    "DECLINE",
    "RE_ACCUMULATION",
)

# Phase -> emoji used by the Mind Map trail integration.
PHASE_EMOJI = {
    "ACCUMULATION": "⏳",
    "MARKUP": "🔄",
    "PARABOLIC": "🚀",
    "DISTRIBUTION": "⚠️",
    "DECLINE": "📉",
    "RE_ACCUMULATION": "🔁",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _coerce_netuid(netuid: Any) -> int:
    if isinstance(netuid, dict):
        netuid = netuid.get("id") or netuid.get("netuid") or netuid.get("subnet") or 0
    try:
        return int(netuid)
    except (TypeError, ValueError):
        try:
            return int(str(netuid))
        except Exception:
            return 0


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return s[lo]
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


class PumpTracker:
    """CUSUM pump-cycle tracker with a 6-phase Wyckoff-style model.

    State is held in memory and persisted to ``data/pump_cycles.json``. The
    tracker is intentionally defensive: every public method swallows internal
    errors so a tracker hiccup can never break the indicator/scheduler loop.
    """

    def __init__(self, state_path: str = STATE_PATH):
        self.state_path = state_path
        self._lock = threading.RLock()
        self._tick = 0
        # netuid -> list of {"t","price","volume","ret"}
        self.snapshots: Dict[int, List[Dict[str, Any]]] = {}
        # netuid -> CUSUM + rolling state
        self.cusum_state: Dict[int, Dict[str, Any]] = {}
        # netuid -> list of completed cycle dicts
        self.cycles: Dict[int, List[Dict[str, Any]]] = {}
        # netuid -> behavioral profile
        self.profiles: Dict[int, Dict[str, Any]] = {}
        # netuid -> cycle accuracy
        self.accuracy: Dict[int, Dict[str, Any]] = {}
        # netuid -> live phase state
        self.phase_state: Dict[int, Dict[str, Any]] = {}
        # netuid -> social sentiment history (Enhancement 2)
        self.sentiment_state: Dict[int, Dict[str, Any]] = {}
        # netuid -> latest technical indicator values (Enhancement 3)
        self.indicator_state: Dict[int, Dict[str, Any]] = {}
        self.meta: Dict[str, Any] = {
            "version": "2.0",
            "created": _now_iso(),
            "last_updated": None,
            "total_snapshots": 0,
            "total_cycles_detected": 0,
        }
        self.load_state()

    # ------------------------------------------------------------------ persistence
    def load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
                self.snapshots = {int(k): v for k, v in (data.get("snapshots") or {}).items()}
                self.cusum_state = {int(k): v for k, v in (data.get("cusum_state") or {}).items()}
                self.cycles = {int(k): v for k, v in (data.get("cycles") or {}).items()}
                self.profiles = {int(k): v for k, v in (data.get("profiles") or {}).items()}
                self.accuracy = {int(k): v for k, v in (data.get("accuracy") or {}).items()}
                self.phase_state = {int(k): v for k, v in (data.get("phase_state") or {}).items()}
                self.sentiment_state = {int(k): v for k, v in (data.get("sentiment_state") or {}).items()}
                self.indicator_state = {int(k): v for k, v in (data.get("indicator_state") or {}).items()}
                self.meta = data.get("meta") or self.meta
        except Exception as exc:
            logger.warning("pump_tracker: load_state failed: %s", exc)

    def save_state(self) -> None:
        with self._lock:
            self.meta["last_updated"] = _now_iso()
            self.meta["total_snapshots"] = sum(len(v) for v in self.snapshots.values())
            self.meta["total_cycles_detected"] = sum(len(v) for v in self.cycles.values())
            data = {
                "snapshots": {str(k): v for k, v in self.snapshots.items()},
                "cusum_state": {str(k): v for k, v in self.cusum_state.items()},
                "cycles": {str(k): v for k, v in self.cycles.items()},
                "profiles": {str(k): v for k, v in self.profiles.items()},
                "accuracy": {str(k): v for k, v in self.accuracy.items()},
                "phase_state": {str(k): v for k, v in self.phase_state.items()},
                "sentiment_state": {str(k): v for k, v in self.sentiment_state.items()},
                "indicator_state": {str(k): v for k, v in self.indicator_state.items()},
                "meta": self.meta,
            }
            try:
                d = os.path.dirname(self.state_path) or "."
                os.makedirs(d, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp, self.state_path)
            except Exception as exc:
                logger.warning("pump_tracker: save_state failed: %s", exc)

    # ------------------------------------------------------------------ snapshot
    def record_price_snapshot(
        self,
        netuid: Any,
        name: Optional[str],
        price: float,
        volume: float = 0.0,
        timestamp: Any = None,
    ) -> None:
        """Record one price observation for a subnet (called every scheduler tick)."""
        try:
            nid = _coerce_netuid(netuid)
            if nid is None or price is None:
                return
            price = float(price or 0.0)
            volume = float(volume or 0.0)
            ts = _parse_ts(timestamp) or datetime.now(timezone.utc)
            with self._lock:
                hist = self.snapshots.setdefault(nid, [])
                prev_price = hist[-1]["price"] if hist else None
                ret = 0.0
                if prev_price and prev_price > 0:
                    ret = (price - prev_price) / prev_price
                hist.append({"t": ts.isoformat(), "price": price, "volume": volume, "ret": ret})
                if len(hist) > MAX_SNAPSHOTS:
                    self.snapshots[nid] = hist[-MAX_SNAPSHOTS:]
                st = self.cusum_state.setdefault(nid, {"name": name or f"SN{nid}", "cusum": 0.0})
                if name:
                    st["name"] = name
                ps = self.phase_state.setdefault(nid, {
                    "netuid": nid,
                    "name": name or f"SN{nid}",
                    "current_phase": "ACCUMULATION",
                    "phase_started": ts.isoformat(),
                    "phase_duration_minutes": 0,
                    "cusum_evidence": 0.0,
                    "cusum_threshold": 0.0,
                    "z_return": 0.0,
                    "rolling_mean": 0.0,
                    "rolling_std": 0.0,
                    "atr_per_bar": 0.0,
                    "is_parabolic": False,
                    "pump_proneness": 0,
                    "cycle_prediction": {},
                    "profile": {},
                    "cycles": [],
                    "cycle_accuracy": {},
                })
                ps["name"] = name or ps.get("name") or f"SN{nid}"
        except Exception as exc:
            logger.warning("pump_tracker: record_price_snapshot failed: %s", exc)

    # ------------------------------------------------------------------ CUSUM
    def update_cusum(self, netuid: Any) -> None:
        """Update the Page CUSUM evidence accumulator for a subnet."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                hist = self.snapshots.get(nid)
                if not hist or len(hist) < 2:
                    return
                returns = [h["ret"] for h in hist[-LOOKBACK:]]
                r_t = returns[-1]
                window = returns[-LOOKBACK:] if len(returns) >= 2 else returns
                mu = _mean(window[:-1]) if len(window) > 1 else 0.0
                sigma = _std(window[:-1]) if len(window) > 2 else _std(window)
                if sigma <= 0:
                    z = 0.0
                else:
                    z = (r_t - mu) / sigma
                st = self.cusum_state.setdefault(nid, {"name": f"SN{nid}", "cusum": 0.0})
                prev_c = float(st.get("cusum", 0.0))
                # Enhancement 1: Volume-Weighted CUSUM.
                # Volume factor = current_volume / avg_volume_last_20_snapshots.
                # Unusual volume AMPLIFIES the pump-detection evidence; normal
                # volume keeps the increment at baseline (factor == 1.0).
                volumes = [float(h.get("volume", 0.0) or 0.0) for h in hist[-LOOKBACK:]]
                current_vol = volumes[-1] if volumes else 0.0
                prior_vols = volumes[:-1]
                if len(prior_vols) >= 20:
                    avg_vol = _mean(prior_vols[-20:])
                elif prior_vols:
                    avg_vol = _mean(prior_vols)
                else:
                    avg_vol = 0.0
                volume_factor = (current_vol / avg_vol) if avg_vol > 0 else 1.0
                # Clamp to a sane range so a single zero/noisy candle can't blow
                # the accumulator up; a 5x spike still multiplies evidence by 5x.
                volume_factor = max(0.0, min(volume_factor, 10.0))
                st["volume_factor"] = round(volume_factor, 3)
                st["volume_spike"] = volume_factor > 2.0
                # Enhancement 4: Adaptive CUSUM k per subnet (default CUSUM_K).
                k = float(st.get("k", CUSUM_K))
                # Volume-weighted evidence increment: z-return scaled by volume.
                c_t = max(0.0, prev_c + (z * volume_factor) - k)
                st["cusum"] = c_t
                st["z_return"] = z
                st["rolling_mean"] = mu
                st["rolling_std"] = sigma
                # Adaptive threshold: rolling 95th percentile of recent CUSUM peaks.
                cusum_history = [float(x) for x in st.get("cusum_history", [])]
                cusum_history.append(c_t)
                if len(cusum_history) > LOOKBACK * 3:
                    cusum_history = cusum_history[-(LOOKBACK * 3):]
                st["cusum_history"] = cusum_history
                threshold = _percentile([v for v in cusum_history if v > 0], 95.0) if any(v > 0 for v in cusum_history) else 1.0
                st["threshold"] = max(threshold, 1.0)
                # ATR-per-bar: |r_t| / avg(|r|) over lookback.
                abs_rets = [abs(x) for x in returns[-LOOKBACK:]]
                avg_abs = _mean(abs_rets[:-1]) if len(abs_rets) > 1 else (abs_rets[0] if abs_rets else 0.0)
                atr_per_bar = (abs(r_t) / avg_abs) if avg_abs > 0 else 0.0
                st["atr_per_bar"] = atr_per_bar
                st["is_parabolic"] = atr_per_bar > PARABOLIC_ATR
        except Exception as exc:
            logger.warning("pump_tracker: update_cusum failed: %s", exc)

    # ------------------------------------------------------------------ phase
    def detect_phase(self, netuid: Any) -> str:
        """Classify the current phase using CUSUM + ATR + price position."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                hist = self.snapshots.get(nid)
                st = self.cusum_state.get(nid)
                ps = self.phase_state.get(nid)
                if not hist or not st or not ps:
                    return "ACCUMULATION"
                c_t = float(st.get("cusum", 0.0))
                threshold = float(st.get("threshold", 1.0))
                atr_per_bar = float(st.get("atr_per_bar", 0.0))
                is_parabolic = bool(st.get("is_parabolic", False))
                prices = [h["price"] for h in hist[-LOOKBACK:]]
                cur_price = prices[-1]
                recent_max = max(prices) if prices else cur_price
                recent_min = min(prices) if prices else cur_price
                price_range = (recent_max - recent_min) if recent_max > 0 else 0.0
                price_flat = price_range <= 0.0 or (price_range / recent_max) < 0.01 if recent_max > 0 else True
                near_peak = cur_price >= (recent_max * 0.97) if recent_max > 0 else False
                rising = len(prices) >= 2 and prices[-1] > prices[-2]
                falling = len(prices) >= 2 and prices[-1] < prices[-2]
                prev_phase = ps.get("current_phase", "ACCUMULATION")

                # Phase classification (priority order).
                if is_parabolic and c_t > threshold * 0.8:
                    new_phase = "PARABOLIC"
                elif c_t > threshold and rising:
                    new_phase = "MARKUP"
                elif near_peak and c_t >= threshold * 0.6 and not rising:
                    new_phase = "DISTRIBUTION"
                elif falling and c_t < threshold * 0.5:
                    new_phase = "DECLINE"
                elif price_flat and c_t < 0.5:
                    # Distinguish first accumulation from re-accumulation after a decline.
                    new_phase = "RE_ACCUMULATION" if prev_phase in ("DECLINE", "DISTRIBUTION") else "ACCUMULATION"
                elif c_t < 0.5 and not rising:
                    new_phase = "RE_ACCUMULATION" if prev_phase in ("DECLINE", "DISTRIBUTION") else "ACCUMULATION"
                else:
                    new_phase = prev_phase

                self._transition_phase(nid, new_phase)
                return new_phase
        except Exception as exc:
            logger.warning("pump_tracker: detect_phase failed: %s", exc)
            return "ACCUMULATION"

    def _transition_phase(self, nid: int, new_phase: str) -> None:
        ps = self.phase_state.get(nid)
        if not ps:
            return
        prev_phase = ps.get("current_phase", "ACCUMULATION")
        now = datetime.now(timezone.utc)
        started = _parse_ts(ps.get("phase_started")) or now
        duration_min = (now - started).total_seconds() / 60.0
        if new_phase != prev_phase:
            # Record phase transition into the in-progress cycle.
            self._on_phase_change(nid, prev_phase, new_phase, duration_min)
            ps["current_phase"] = new_phase
            ps["phase_started"] = now.isoformat()
            ps["phase_duration_minutes"] = 0.0
        else:
            ps["phase_duration_minutes"] = round(duration_min, 1)
        # Mirror live CUSUM/ATR state into the phase_state snapshot.
        st = self.cusum_state.get(nid, {})
        ps["cusum_evidence"] = round(float(st.get("cusum", 0.0)), 3)
        ps["cusum_threshold"] = round(float(st.get("threshold", 0.0)), 3)
        ps["z_return"] = round(float(st.get("z_return", 0.0)), 3)
        ps["rolling_mean"] = round(float(st.get("rolling_mean", 0.0)), 4)
        ps["rolling_std"] = round(float(st.get("rolling_std", 0.0)), 4)
        ps["atr_per_bar"] = round(float(st.get("atr_per_bar", 0.0)), 3)
        ps["is_parabolic"] = bool(st.get("is_parabolic", False))

    def _on_phase_change(self, nid: int, prev_phase: str, new_phase: str, duration_min: float) -> None:
        """Maintain an in-progress cycle and close it when the cycle completes."""
        ps = self.phase_state.get(nid)
        if not ps:
            return
        in_prog = ps.setdefault("_in_progress", {})
        seq = in_prog.setdefault("phase_sequence", [])
        if not seq or seq[-1] != prev_phase:
            seq.append(prev_phase)
        # Track pump leg (MARKUP/PARABOLIC) magnitude + duration.
        if prev_phase in ("MARKUP", "PARABOLIC") and new_phase in ("DISTRIBUTION", "DECLINE"):
            hist = self.snapshots.get(nid, [])
            if hist:
                pump_start_idx = in_prog.get("pump_start_idx")
                if pump_start_idx is not None:
                    leg_prices = [h["price"] for h in hist[pump_start_idx:]]
                    if leg_prices:
                        start_p = leg_prices[0]
                        peak_p = max(leg_prices)
                        in_prog["pump_peak_price"] = peak_p
                        in_prog["pump_magnitude_pct"] = round((peak_p - start_p) / start_p * 100, 2) if start_p > 0 else 0.0
                        in_prog["pump_duration_minutes"] = round(duration_min, 1)
        if new_phase in ("MARKUP", "PARABOLIC") and prev_phase not in ("MARKUP", "PARABOLIC"):
            hist = self.snapshots.get(nid, [])
            in_prog["pump_start_idx"] = max(0, len(hist) - 1)
            in_prog["pump_start_ts"] = _now_iso()

        # A cycle "completes" when we return to ACCUMULATION/RE_ACCUMULATION after a decline.
        if new_phase in ("ACCUMULATION", "RE_ACCUMULATION") and "DECLINE" in seq:
            self._close_cycle(nid, in_prog, new_phase)
            ps["_in_progress"] = {}

    def _close_cycle(self, nid: int, in_prog: Dict[str, Any], new_phase: str) -> None:
        cycles = self.cycles.setdefault(nid, [])
        cycle_id = len(cycles) + 1
        hist = self.snapshots.get(nid, [])
        pump_start_ts = in_prog.get("pump_start_ts")
        pump_peak_price = in_prog.get("pump_peak_price")
        pump_mag = in_prog.get("pump_magnitude_pct", 0.0)
        pump_dur = in_prog.get("pump_duration_minutes", 0.0)
        # Consolidation depth: drop from peak to current.
        consolidation_depth = 0.0
        if hist and pump_peak_price:
            cur = hist[-1]["price"]
            consolidation_depth = round((cur - pump_peak_price) / pump_peak_price * 100, 2)
        total_dur = 0.0
        cycle = {
            "cycle_id": cycle_id,
            "phase_sequence": in_prog.get("phase_sequence", []),
            "pump_start": pump_start_ts,
            "pump_peak": None,
            "pump_duration_minutes": round(pump_dur, 1),
            "pump_magnitude_pct": round(pump_mag, 2),
            "peak_proneness_at_peak": in_prog.get("peak_proneness", 0),
            "consolidation_duration_minutes": 0.0,
            "consolidation_depth_pct": consolidation_depth,
            "re_pump": False,
            "re_pump_magnitude_pct": 0.0,
            "total_cycle_duration_minutes": round(total_dur, 1),
            "closed_at": _now_iso(),
        }
        cycles.append(cycle)
        if len(cycles) > 50:
            self.cycles[nid] = cycles[-50:]
        # Recompute profile now that a cycle closed.
        self.compute_profile(nid)

    # ------------------------------------------------------------------ proneness
    def compute_proneness(self, netuid: Any) -> int:
        """Compute a 0-100 pump proneness score for a subnet."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                cycles = self.cycles.get(nid, [])
                st = self.cusum_state.get(nid, {})
                ps = self.phase_state.get(nid, {})
                hist = self.snapshots.get(nid, [])
                # Frequency component: more observed cycles -> more prone.
                freq = min(len(cycles) / 10.0, 1.0)
                # Magnitude component: average pump magnitude normalized.
                avg_mag = _mean([c.get("pump_magnitude_pct", 0) for c in cycles]) if cycles else 0.0
                mag = min(avg_mag / 25.0, 1.0)
                # Current evidence relative to threshold.
                c_t = float(st.get("cusum", 0.0))
                threshold = float(st.get("threshold", 1.0)) or 1.0
                evidence = min(c_t / threshold, 1.0)
                # Volatility regime: higher rolling std -> more prone.
                sigma = float(st.get("rolling_std", 0.0))
                vol = min(sigma / 0.05, 1.0) if sigma > 0 else 0.0
                # Cycle accuracy feedback: accurate trackers get a small boost.
                acc = self.accuracy.get(nid, {})
                acc_score = float(acc.get("accuracy_score", 0.0))
                acc_boost = acc_score * 0.1
                score = (
                    0.30 * freq
                    + 0.25 * mag
                    + 0.20 * evidence
                    + 0.15 * vol
                    + 0.10 * (0.5 + acc_boost)
                )
                base_score = max(0.0, min(1.0, score)) * 100.0
                # Enhancement 1: volume spike boosts proneness by +12 points.
                if bool(st.get("volume_spike", False)):
                    base_score = min(100.0, base_score + 12.0)
                # Enhancement 2: social sentiment momentum multiplier.
                sentiment_factor = self.get_sentiment_factor(nid)
                base_score = base_score * sentiment_factor
                # Enhancement 3: multi-signal convergence from technical indicators.
                convergence = self.compute_signal_convergence(nid)
                base_score = base_score * (0.5 + 0.5 * convergence)
                proneness = int(round(max(0.0, min(100.0, base_score))))
                if ps:
                    ps["pump_proneness"] = proneness
                    ps["signal_convergence"] = round(convergence, 3)
                    ps["sentiment_factor"] = round(sentiment_factor, 3)
                return proneness
        except Exception as exc:
            logger.warning("pump_tracker: compute_proneness failed: %s", exc)
            return 0

    # ------------------------------------------------------------------ prediction
    def predict_next_cycle(self, netuid: Any) -> Dict[str, Any]:
        """Predict timing/duration/magnitude of the next pump for a subnet."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                cycles = self.cycles.get(nid, [])
                profile = self.profiles.get(nid, {})
                n = len(cycles)
                if n == 0:
                    pred = {
                        "next_pump_expected_hours": None,
                        "expected_pump_duration_minutes": None,
                        "expected_pump_magnitude_pct": None,
                        "prediction_confidence": 0.0,
                        "confidence_basis": "no historical cycles yet",
                    }
                else:
                    avg_period = profile.get("avg_cycle_period", 0.0) or _mean(
                        [c.get("total_cycle_duration_minutes", 0) for c in cycles]
                    )
                    avg_dur = profile.get("avg_pump_duration", 0.0) or _mean(
                        [c.get("pump_duration_minutes", 0) for c in cycles]
                    )
                    avg_mag = profile.get("avg_pump_magnitude", 0.0) or _mean(
                        [c.get("pump_magnitude_pct", 0) for c in cycles]
                    )
                    # Confidence grows with sample size, capped.
                    confidence = round(min(0.30 + 0.10 * n, 0.90), 2)
                    pred = {
                        "next_pump_expected_hours": round(avg_period / 60.0, 2) if avg_period else None,
                        "expected_pump_duration_minutes": round(avg_dur, 1) if avg_dur else None,
                        "expected_pump_magnitude_pct": round(avg_mag, 2) if avg_mag else None,
                        "prediction_confidence": confidence,
                        "confidence_basis": f"based on {n} historical cycle{'s' if n != 1 else ''}",
                    }
                ps = self.phase_state.get(nid)
                if ps:
                    ps["cycle_prediction"] = pred
                return pred
        except Exception as exc:
            logger.warning("pump_tracker: predict_next_cycle failed: %s", exc)
            return {}

    # ------------------------------------------------------------------ profile
    def compute_profile(self, netuid: Any) -> Dict[str, Any]:
        """Aggregate cycle history into a behavioral profile + transition matrix."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                cycles = self.cycles.get(nid, [])
                n = len(cycles)
                pump_durs = [c.get("pump_duration_minutes", 0) for c in cycles]
                mags = [c.get("pump_magnitude_pct", 0) for c in cycles]
                cons_durs = [c.get("consolidation_duration_minutes", 0) for c in cycles]
                total_durs = [c.get("total_cycle_duration_minutes", 0) for c in cycles]
                re_pumps = [c for c in cycles if c.get("re_pump")]
                # Phase transition matrix from observed phase sequences.
                matrix: Dict[str, Dict[str, float]] = {p: {} for p in PHASES}
                counts: Dict[str, Dict[str, int]] = {p: {} for p in PHASES}
                for c in cycles:
                    seq = c.get("phase_sequence", [])
                    for a, b in zip(seq, seq[1:]):
                        counts.setdefault(a, {}).setdefault(b, 0)
                        counts[a][b] += 1
                for a, nxt in counts.items():
                    total = sum(nxt.values()) or 1
                    matrix[a] = {b: round(c / total, 2) for b, c in nxt.items()}
                # Ensure self-loop defaults so the matrix is never empty.
                for p in PHASES:
                    matrix.setdefault(p, {})
                    if not matrix[p]:
                        matrix[p] = {p: 1.0}

                avg_period = _mean(total_durs) if total_durs else 0.0
                proneness = self.compute_proneness(nid)
                # Typical pattern string from the most recent cycle's sequence.
                last_seq = cycles[-1].get("phase_sequence", []) if cycles else []
                typical = " → ".join(f"{p.lower()}_{ '0h' }" for p in last_seq) if last_seq else "insufficient data"
                profile = {
                    "avg_pump_duration": round(_mean(pump_durs), 1) if pump_durs else 0,
                    "avg_consolidation_duration": round(_mean(cons_durs), 1) if cons_durs else 0,
                    "avg_pump_magnitude": round(_mean(mags), 2) if mags else 0,
                    "re_pump_rate": round(len(re_pumps) / n, 2) if n else 0.0,
                    "avg_cycle_period": round(avg_period, 1),
                    "total_cycles_observed": n,
                    "proneness_score": proneness,
                    "typical_pattern": typical,
                    "phase_transition_matrix": matrix,
                }
                self.profiles[nid] = profile
                ps = self.phase_state.get(nid)
                if ps:
                    ps["profile"] = profile
                return profile
        except Exception as exc:
            logger.warning("pump_tracker: compute_profile failed: %s", exc)
            return {}

    # ------------------------------------------------------------------ outcomes
    def record_cycle_outcome(self, netuid: Any, prediction: Dict[str, Any], actual: Dict[str, Any]) -> None:
        """Record whether a cycle prediction was correct; feeds back into proneness."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                acc = self.accuracy.setdefault(nid, {
                    "predictions_made": 0,
                    "timing_correct": 0,
                    "direction_correct": 0,
                    "magnitude_error_avg": 0.0,
                    "accuracy_score": 0.0,
                })
                acc["predictions_made"] = int(acc.get("predictions_made", 0)) + 1
                pred_dir = str(prediction.get("predicted_direction", "")).lower()
                act_dir = str(actual.get("actual_direction", "")).lower()
                if pred_dir and act_dir and pred_dir == act_dir:
                    acc["direction_correct"] = int(acc.get("direction_correct", 0)) + 1
                pred_timing = float(prediction.get("predicted_timing") or 0)
                act_timing = float(actual.get("actual_timing") or 0)
                if pred_timing > 0 and act_timing > 0:
                    if abs(act_timing - pred_timing) / pred_timing <= 0.30:
                        acc["timing_correct"] = int(acc.get("timing_correct", 0)) + 1
                pred_mag = float(prediction.get("predicted_magnitude") or 0)
                act_mag = float(actual.get("actual_magnitude") or 0)
                mag_err = abs(act_mag - pred_mag)
                prev_errs = float(acc.get("magnitude_error_avg", 0.0)) * (int(acc.get("predictions_made", 1)) - 1)
                acc["magnitude_error_avg"] = round((prev_errs + mag_err) / int(acc.get("predictions_made", 1)), 2)
                made = max(int(acc.get("predictions_made", 1)), 1)
                acc["accuracy_score"] = round(
                    (int(acc.get("direction_correct", 0)) + int(acc.get("timing_correct", 0))) / (2 * made), 3
                )
                ps = self.phase_state.get(nid)
                if ps:
                    ps["cycle_accuracy"] = dict(acc)
        except Exception as exc:
            logger.warning("pump_tracker: record_cycle_outcome failed: %s", exc)

    # ------------------------------------------------------------------ sentiment (Enhancement 2)
    def update_sentiment(self, netuid: Any, sentiment_score: Optional[float] = None, mention_count: Optional[int] = None) -> None:
        """Update social sentiment data for a subnet.

        Called from server.py whenever sentiment data is available. Keeps a
        rolling window of the last 20 scores/mentions so momentum can be
        derived without storing unbounded history.
        """
        try:
            nid = _coerce_netuid(netuid)
            if nid is None:
                return
            with self._lock:
                st = self.sentiment_state.setdefault(nid, {"scores": [], "mentions": []})
                if sentiment_score is not None:
                    st["scores"].append(float(sentiment_score))
                    if len(st["scores"]) > 20:
                        st["scores"].pop(0)
                if mention_count is not None:
                    st["mentions"].append(int(mention_count))
                    if len(st["mentions"]) > 20:
                        st["mentions"].pop(0)
        except Exception as exc:
            logger.warning("pump_tracker: update_sentiment failed: %s", exc)

    def get_sentiment_factor(self, netuid: Any) -> float:
        """Return a sentiment momentum multiplier for proneness scoring.

        Positive sentiment momentum (recent scores rising vs older scores)
        amplifies proneness; negative momentum dampens it. Clamped to 0.5-1.5.
        Returns 1.0 (neutral) when there is insufficient history.
        """
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                scores = self.sentiment_state.get(nid, {}).get("scores", [])
                if len(scores) < 3:
                    return 1.0
                recent_avg = _mean(scores[-3:])
                older_window = scores[-6:-3] if len(scores) >= 6 else scores[:-3]
                older_avg = _mean(older_window) if older_window else _mean(scores[:-3] or [0.0])
                momentum = recent_avg - older_avg
                factor = 1.0 + max(-0.5, min(0.5, momentum * 0.3))
                return float(factor)
        except Exception as exc:
            logger.warning("pump_tracker: get_sentiment_factor failed: %s", exc)
            return 1.0

    # ------------------------------------------------------------------ indicators (Enhancement 3)
    def update_indicators(self, netuid: Any, indicator_values: Optional[Dict[str, Any]] = None) -> None:
        """Cache the latest technical indicator values for a subnet.

        ``indicator_values`` is the dict produced by server.py's
        ``_compute_technical_indicators`` (nested ``{value, signal}`` shape) or
        the flat shape from the indicator engine. Stored verbatim so
        ``compute_signal_convergence`` can read it next tick.
        """
        try:
            nid = _coerce_netuid(netuid)
            if nid is None or not indicator_values:
                return
            with self._lock:
                self.indicator_state[nid] = dict(indicator_values)
        except Exception as exc:
            logger.warning("pump_tracker: update_indicators failed: %s", exc)

    def _read_indicator_state_file(self, nid: int) -> Dict[str, Any]:
        """Fallback: read indicator values from data/indicator_state.json."""
        try:
            path = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            per = data.get("per_subnet", {}).get(str(nid), {})
            return {
                "rsi": per.get("rsi"),
                "macd_histogram": per.get("macd_histogram"),
                "stochastic_k": per.get("stochastic_k"),
            }
        except Exception:
            return {}

    @staticmethod
    def _ind_value(ind: Dict[str, Any], key: str) -> Optional[float]:
        """Extract a numeric indicator value from either nested or flat shape."""
        v = ind.get(key)
        if v is None:
            return None
        if isinstance(v, dict):
            v = v.get("value", v.get("rsi", v.get("histogram", v.get("k"))))
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def compute_signal_convergence(self, netuid: Any, indicator_values: Optional[Dict[str, Any]] = None) -> float:
        """Compute a 0-1 multi-signal convergence score from technical indicators.

        Counts how many of 7 indicators are bullish:
          RSI oversold (<30) or bullish (>50 & rising)
          MACD histogram positive
          Stochastic oversold (<20)
          MFI oversold (<30) or bullish (>50)
          CCI oversold (<-100)
          Williams %R oversold (<-80)
          Bollinger position near lower band (<0.2)
        Returns bullish_count / 7, or 0.5 (neutral) when no data is available.
        """
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                if indicator_values is None:
                    indicator_values = self.indicator_state.get(nid)
                if not indicator_values:
                    indicator_values = self._read_indicator_state_file(nid)
                if not indicator_values:
                    return 0.5

                bullish_count = 0
                total_indicators = 7

                rsi = self._ind_value(indicator_values, "rsi")
                rsi_prev = self._ind_value(indicator_values, "rsi_prev")
                if rsi is not None:
                    if rsi < 30 or (rsi > 50 and (rsi_prev is None or rsi > rsi_prev)):
                        bullish_count += 1

                macd_hist = self._ind_value(indicator_values, "macd_histogram")
                if macd_hist is None:
                    macd_hist = self._ind_value(indicator_values, "macd")
                if macd_hist is not None and macd_hist > 0:
                    bullish_count += 1

                stoch = self._ind_value(indicator_values, "stochastic")
                if stoch is None:
                    stoch = self._ind_value(indicator_values, "stochastic_k")
                if stoch is not None and stoch < 20:
                    bullish_count += 1

                mfi = self._ind_value(indicator_values, "mfi")
                if mfi is not None and (mfi < 30 or mfi > 50):
                    bullish_count += 1

                cci = self._ind_value(indicator_values, "cci")
                if cci is not None and cci < -100:
                    bullish_count += 1

                williams = self._ind_value(indicator_values, "williams_r")
                if williams is not None and williams < -80:
                    bullish_count += 1

                bb_position = self._ind_value(indicator_values, "bollinger_position")
                if bb_position is None:
                    bb = indicator_values.get("bollinger")
                    if isinstance(bb, dict):
                        bb_position = bb.get("position")
                        try:
                            bb_position = float(bb_position) if bb_position is not None else None
                        except (TypeError, ValueError):
                            bb_position = None
                if bb_position is not None and bb_position < 0.2:
                    bullish_count += 1

                return float(bullish_count) / float(total_indicators)
        except Exception as exc:
            logger.warning("pump_tracker: compute_signal_convergence failed: %s", exc)
            return 0.5

    # ------------------------------------------------------------------ adaptive params (Enhancement 4)
    def adapt_parameters(self, netuid: Any) -> None:
        """Adapt CUSUM k per subnet based on prediction accuracy.

        Low accuracy (<40%) lowers k toward 0.2 to be more sensitive to smaller
        pumps; high accuracy (>70%) leaves parameters stable. Requires at least
        10 predictions before adapting. Records an ``adaptation_note``.
        """
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                acc = self.accuracy.get(nid, {})
                predictions_made = int(acc.get("predictions_made", 0) or 0)
                if predictions_made < 10:
                    return
                accuracy_score = float(acc.get("accuracy_score", 0.5) or 0.5)
                st = self.cusum_state.setdefault(nid, {"name": f"SN{nid}", "cusum": 0.0})
                current_k = float(st.get("k", CUSUM_K))
                if accuracy_score < 0.4:
                    new_k = max(0.2, current_k - 0.1)
                    st["k"] = new_k
                    st["adapted_k"] = new_k
                    st["adaptation_note"] = f"k lowered to {new_k:.2f} due to low accuracy ({accuracy_score:.0%})"
                elif accuracy_score > 0.7:
                    st["adaptation_note"] = f"parameters stable, accuracy good ({accuracy_score:.0%})"
                # High false-positive handling would require separate FP
                # tracking; left as a future hook when that data exists.
        except Exception as exc:
            logger.warning("pump_tracker: adapt_parameters failed: %s", exc)

    # ------------------------------------------------------------------ accessors
    def get_current_phase(self, netuid: Any) -> str:
        nid = _coerce_netuid(netuid)
        with self._lock:
            return self.phase_state.get(nid, {}).get("current_phase", "ACCUMULATION")

    def get_proneness(self, netuid: Any) -> int:
        nid = _coerce_netuid(netuid)
        with self._lock:
            return int(self.phase_state.get(nid, {}).get("pump_proneness", 0))

    def get_cycle_context(self, netuid: Any) -> str:
        """Return a short Mind-Map-style cycle context string for a subnet."""
        try:
            nid = _coerce_netuid(netuid)
            with self._lock:
                ps = self.phase_state.get(nid)
                if not ps:
                    return ""
                phase = ps.get("current_phase", "ACCUMULATION")
                emoji = PHASE_EMOJI.get(phase, "🔄")
                dur = ps.get("phase_duration_minutes", 0)
                proneness = ps.get("pump_proneness", 0)
                pred = ps.get("cycle_prediction", {}) or {}
                # Enhancement 1/2/3: append volume, sentiment, convergence
                # signal tags to the Mind Map trail cycle context.
                st = self.cusum_state.get(nid, {})
                sig_tags: List[str] = []
                if bool(st.get("volume_spike", False)):
                    sig_tags.append("📊vol_spike")
                sentiment_factor = float(ps.get("sentiment_factor", self.get_sentiment_factor(nid)))
                if sentiment_factor > 1.05:
                    sig_tags.append("📈sentiment+")
                elif sentiment_factor < 0.95:
                    sig_tags.append("📉sentiment-")
                convergence = float(ps.get("signal_convergence", self.compute_signal_convergence(nid)))
                sig_tags.append(f"convergence {int(round(convergence * 100))}%")
                sig_suffix = (" " + " ".join(sig_tags)) if sig_tags else ""
                if phase == "MARKUP":
                    peak_in = pred.get("expected_pump_duration_minutes")
                    tail = f", peak expected in ~{int(peak_in)}min" if peak_in else ""
                    return f"→ {emoji} MARKUP phase ({int(dur)}min), proneness {proneness}/100{tail}{sig_suffix}"
                if phase == "ACCUMULATION":
                    nxt = pred.get("next_pump_expected_hours")
                    tail = f", next pump expected in ~{nxt}h" if nxt else ""
                    return f"→ {emoji} ACCUMULATION phase ({int(dur)}min){tail}, proneness {proneness}/100{sig_suffix}"
                if phase == "DISTRIBUTION":
                    return f"→ {emoji} DISTRIBUTION phase ({int(dur)}min), pump may be ending, proneness {proneness}/100{sig_suffix}"
                if phase == "PARABOLIC":
                    return f"→ {emoji} PARABOLIC phase ({int(dur)}min), extreme acceleration, proneness {proneness}/100{sig_suffix}"
                if phase == "DECLINE":
                    return f"→ {emoji} DECLINE phase ({int(dur)}min), proneness {proneness}/100{sig_suffix}"
                if phase == "RE_ACCUMULATION":
                    nxt = pred.get("next_pump_expected_hours")
                    tail = f", next pump expected in ~{nxt}h" if nxt else ""
                    return f"→ {emoji} RE-ACCUMULATION phase ({int(dur)}min){tail}, proneness {proneness}/100{sig_suffix}"
                return f"→ {emoji} {phase} phase ({int(dur)}min), proneness {proneness}/100{sig_suffix}"
        except Exception:
            return ""

    # ------------------------------------------------------------------ aggregate
    def get_all_analytics(self) -> Dict[str, Any]:
        """Return all analytics for the /api/pump-analytics endpoint."""
        with self._lock:
            subnets: List[Dict[str, Any]] = []
            for nid, ps in self.phase_state.items():
                cycles = self.cycles.get(nid, [])
                acc = self.accuracy.get(nid, {})
                st = self.cusum_state.get(nid, {})
                convergence = float(ps.get("signal_convergence", self.compute_signal_convergence(nid)))
                sentiment_factor = float(ps.get("sentiment_factor", self.get_sentiment_factor(nid)))
                subnets.append({
                    "netuid": nid,
                    "name": ps.get("name", f"SN{nid}"),
                    "current_phase": ps.get("current_phase", "ACCUMULATION"),
                    "phase_started": ps.get("phase_started"),
                    "phase_duration_minutes": ps.get("phase_duration_minutes", 0),
                    "cusum_evidence": ps.get("cusum_evidence", 0.0),
                    "cusum_threshold": ps.get("cusum_threshold", 0.0),
                    "z_return": ps.get("z_return", 0.0),
                    "rolling_mean": ps.get("rolling_mean", 0.0),
                    "rolling_std": ps.get("rolling_std", 0.0),
                    "atr_per_bar": ps.get("atr_per_bar", 0.0),
                    "is_parabolic": ps.get("is_parabolic", False),
                    "pump_proneness": ps.get("pump_proneness", 0),
                    "cycle_prediction": ps.get("cycle_prediction", {}),
                    "profile": ps.get("profile", {}),
                    "cycles": cycles[-10:],
                    "cycle_accuracy": acc,
                    # Enhancement 1: volume-weighted CUSUM
                    "volume_factor": round(float(st.get("volume_factor", 1.0)), 3),
                    "volume_spike": bool(st.get("volume_spike", False)),
                    # Enhancement 2: social sentiment
                    "sentiment_factor": round(sentiment_factor, 3),
                    # Enhancement 3: multi-signal convergence
                    "signal_convergence": round(convergence, 3),
                    # Enhancement 4: adaptive CUSUM parameters
                    "adapted_k": st.get("adapted_k") if st.get("adapted_k") is not None else st.get("k", CUSUM_K),
                    "adaptation_note": st.get("adaptation_note", ""),
                })
            subnets.sort(key=lambda s: s.get("pump_proneness", 0), reverse=True)
            total_cycles = sum(len(v) for v in self.cycles.values())
            avg_proneness = round(_mean([s.get("pump_proneness", 0) for s in subnets]), 1) if subnets else 0.0
            top_candidates = [s["netuid"] for s in subnets[:5]]
            return {
                "status": "success",
                "data": {
                    "subnets": subnets,
                    "meta": {
                        "tracked_subnets": len(subnets),
                        "total_cycles": total_cycles,
                        "avg_proneness": avg_proneness,
                        "top_pump_candidates": top_candidates,
                        "updated_at": self.meta.get("last_updated") or _now_iso(),
                    },
                },
            }

    # ------------------------------------------------------------------ scheduler hook
    def on_tick(self, netuid: Any, name: Optional[str], price: float, volume: float = 0.0, timestamp: Any = None) -> None:
        """Convenience hook: record snapshot, update CUSUM, detect phase.

        Heavy proneness/prediction/profile computations run every PRONENESS_TICKS.
        """
        try:
            self.record_price_snapshot(netuid, name, price, volume, timestamp)
            self.update_cusum(netuid)
            self.detect_phase(netuid)
            with self._lock:
                self._tick += 1
                due = (self._tick % PRONENESS_TICKS) == 0
                adapt_due = (self._tick % 10) == 0
            if due:
                self.compute_proneness(netuid)
                self.predict_next_cycle(netuid)
                self.compute_profile(netuid)
                self.save_state()
            # Enhancement 4: adapt CUSUM k every 10th tick per subnet.
            if adapt_due:
                self.adapt_parameters(netuid)
        except Exception as exc:
            logger.warning("pump_tracker: on_tick failed: %s", exc)


# ------------------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------------------
_tracker: Optional[PumpTracker] = None
_tracker_lock = threading.Lock()


def get_pump_tracker() -> PumpTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = PumpTracker()
        return _tracker
