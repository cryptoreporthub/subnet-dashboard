"""Pump cycle analytics engine — 5-phase conviction ladder.

Implements a composite pump score (volume Z-score, 1-minute momentum, order-flow
imbalance), Bayesian judge-weighted final score, exponential-decay re-pump
probability, CUSUM change-point detection, and per-subnet behavioral profiles.
State is persisted to ``data/pump_cycles.json`` using the existing v2 schema.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

STATE_PATH = os.environ.get("PUMP_TRACKER_STATE_PATH", "data/pump_cycles.json")
MAX_SNAPSHOTS = 60
VOLUME_WINDOW = 30
PHASE_LOCK_MINUTES = 15
STATE_VERSION = "2.0"

PHASES = {
    "INACTIVE": 0.00,
    "EARLY": 0.30,
    "EXHAUSTING": 0.50,
    "CONSOLIDATING": 0.60,
    "SECOND_WIND": 0.70,
    "SELL": 0.85,
}

_PHASE_ORDER = ["INACTIVE", "EARLY", "EXHAUSTING", "CONSOLIDATING", "SECOND_WIND", "SELL"]


class PumpTracker:
    """Rolling-window pump-cycle tracker with phase-lock and CUSUM detection."""

    def __init__(self, state_path: Optional[str] = None) -> None:
        self._path = state_path or STATE_PATH
        self._lock = threading.RLock()
        self._snapshots: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        self._phase_state: Dict[Any, Dict[str, Any]] = {}
        self._cusum_state: Dict[Any, Dict[str, Any]] = {}
        self._cycles: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        self._profiles: Dict[Any, Dict[str, Any]] = {}
        self._accuracy: Dict[Any, Dict[str, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"correct": 0, "total": 0})
        )
        self._meta: Dict[str, Any] = {"version": STATE_VERSION}
        self._load_state()

    # ------------------------------------------------------------------
    # Snapshot ingestion
    # ------------------------------------------------------------------
    def record_snapshot(
        self,
        netuid: Any,
        price: float,
        volume: float,
        buy_volume: float = 0.0,
        sell_volume: float = 0.0,
        timestamp: Optional[datetime] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a price/volume tick and update all derived analytics."""
        with self._lock:
            self._ensure_netuid(netuid, name)
            now = timestamp or datetime.now(timezone.utc)
            snapshots = self._snapshots[netuid]

            ret_1m = self._compute_return(price, snapshots)
            z_vol = self._compute_z_volume(volume, snapshots)
            buy_ratio = self._compute_buy_ratio(buy_volume, sell_volume, snapshots)
            pump_score = self._compute_pump_score(z_vol, ret_1m, buy_ratio)

            oracle = pulse = echo = 0.5
            final_score = self.compute_final_score(pump_score, oracle, pulse, echo)
            re_pump_prob = self._compute_re_pump_prob(netuid, pump_score, now)

            snapshot = {
                "timestamp": now.isoformat(),
                "price": float(price),
                "volume": float(volume),
                "buy_volume": float(buy_volume),
                "sell_volume": float(sell_volume),
                "z_vol": round(z_vol, 4),
                "ret_1m": round(ret_1m, 6),
                "buy_ratio": round(buy_ratio, 4),
                "pump_score": round(pump_score, 4),
                "final_score": round(final_score, 4),
                "re_pump_prob": round(re_pump_prob, 4),
            }
            snapshots.append(snapshot)
            if len(snapshots) > MAX_SNAPSHOTS:
                snapshots.pop(0)

            self._update_cusum(netuid, pump_score)
            old_phase = self._phase_state[netuid].get("phase", "INACTIVE")
            new_phase = self._detect_phase(netuid, final_score, now)
            self._update_cycles(netuid, old_phase, new_phase, now)
            self._compute_profile(netuid)

            self._meta["last_updated"] = now.isoformat()
            self._save_state()

            return snapshot

    def on_tick(
        self,
        netuid: Any,
        name: Optional[str] = None,
        price: float = 0.0,
        volume: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Alias used by the indicator engine hook."""
        return self.record_snapshot(
            netuid=netuid,
            price=price,
            volume=volume,
            buy_volume=0.0,
            sell_volume=0.0,
            timestamp=timestamp,
            name=name,
        )

    def record_price_snapshot(
        self,
        netuid: Any,
        price: float,
        volume: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible alias for callers that only have price/volume."""
        return self.record_snapshot(
            netuid=netuid,
            price=price,
            volume=volume,
            buy_volume=0.0,
            sell_volume=0.0,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Core formulas
    # ------------------------------------------------------------------
    @staticmethod
    def compute_final_score(
        pump_score: float,
        oracle_score: float = 0.5,
        pulse_score: float = 0.5,
        echo_score: float = 0.5,
    ) -> float:
        """Bayesian judge-weighted integration."""
        return (0.5 * oracle_score + 0.3 * pulse_score + 0.2 * echo_score + pump_score) / 2.0

    @staticmethod
    def _compute_pump_score(z_vol: float, ret_1m: float, buy_ratio: float) -> float:
        term_vol = min(z_vol / 3.0, 1.0)
        term_ret = min(max(ret_1m / 0.02, 0.0), 1.0)
        term_flow = max(buy_ratio - 0.5, 0.0)
        return 0.4 * term_vol + 0.4 * term_ret + 0.2 * term_flow

    def _compute_return(self, price: float, snapshots: List[Dict[str, Any]]) -> float:
        if not snapshots or snapshots[-1].get("price", 0) <= 0 or price <= 0:
            return 0.0
        prev = snapshots[-1]["price"]
        return (price - prev) / prev

    def _compute_z_volume(self, volume: float, snapshots: List[Dict[str, Any]]) -> float:
        volumes = [s["volume"] for s in snapshots[-VOLUME_WINDOW:]]
        if len(volumes) < 2:
            return 0.0
        try:
            m = mean(volumes)
            s = stdev(volumes)
        except Exception:
            return 0.0
        if s == 0:
            return 0.0
        return (volume - m) / s

    def _compute_buy_ratio(
        self,
        buy_volume: float,
        sell_volume: float,
        snapshots: List[Dict[str, Any]],
    ) -> float:
        total = buy_volume + sell_volume
        if total > 0:
            return buy_volume / total
        # Fallback: infer from recent price direction when order-flow is absent.
        if len(snapshots) >= 2:
            prev, curr = snapshots[-2]["price"], snapshots[-1]["price"]
            if prev > 0 and curr > prev:
                return 0.55
            if prev > 0 and curr < prev:
                return 0.45
        return 0.5

    # ------------------------------------------------------------------
    # CUSUM change-point detection
    # ------------------------------------------------------------------
    def _update_cusum(self, netuid: Any, pump_score: float) -> None:
        st = self._cusum_state[netuid]
        scores = [s["pump_score"] for s in self._snapshots[netuid][-30:]]
        if len(scores) < 2:
            st["mean"] = pump_score
            st["std"] = 0.0
            st["cusum_pos"] = 0.0
            st["cusum_neg"] = 0.0
            return
        m = mean(scores)
        try:
            s = stdev(scores)
        except Exception:
            s = 0.0
        if s == 0:
            s = 0.01
        k = 0.5 * s
        st["mean"] = m
        st["std"] = s
        st["cusum_pos"] = max(0.0, st.get("cusum_pos", 0.0) + (pump_score - m) - k)
        st["cusum_neg"] = min(0.0, st.get("cusum_neg", 0.0) + (pump_score - m) + k)
        st["cusum"] = st["cusum_pos"] - st["cusum_neg"]

    def update_cusum(self, netuid: Any, pump_score: float) -> None:
        """Public alias for CUSUM updates."""
        with self._lock:
            self._ensure_netuid(netuid)
            self._update_cusum(netuid, pump_score)

    # ------------------------------------------------------------------
    # Phase detection with minimum lock
    # ------------------------------------------------------------------
    def _detect_phase(self, netuid: Any, final_score: float, now: datetime) -> str:
        ps = self._phase_state[netuid]
        current = ps.get("phase", "INACTIVE")
        since = ps.get("since")

        # Determine target phase from final score thresholds.
        target = "INACTIVE"
        for phase in _PHASE_ORDER:
            if final_score >= PHASES[phase]:
                target = phase

        if current == target:
            ps["duration_min"] = self._minutes_between(since, now)
            return current

        locked = since is not None and self._minutes_between(since, now) < PHASE_LOCK_MINUTES
        # Allow immediate transition out of INACTIVE so the tracker can wake up.
        if current != "INACTIVE" and locked:
            ps["duration_min"] = self._minutes_between(since, now)
            return current

        ps["phase"] = target
        ps["since"] = now.isoformat()
        ps["duration_min"] = 0.0
        ps["last_transition"] = now.isoformat()
        return target

    def detect_phase(self, netuid: Any, score: Optional[float] = None) -> str:
        """Public alias to (re)detect phase for a subnet."""
        with self._lock:
            self._ensure_netuid(netuid)
            if score is None:
                score = self._last_final_score(netuid)
            return self._detect_phase(netuid, score, datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Cycle / profile bookkeeping
    # ------------------------------------------------------------------
    def _update_cycles(self, netuid: Any, old_phase: str, new_phase: str, now: datetime) -> None:
        if old_phase == new_phase:
            return
        cycles = self._cycles[netuid]
        snapshots = self._snapshots[netuid]
        max_score = max((s["pump_score"] for s in snapshots), default=0.0)
        cycles.append(
            {
                "start": snapshots[0]["timestamp"] if snapshots else now.isoformat(),
                "end": now.isoformat(),
                "start_phase": old_phase,
                "end_phase": new_phase,
                "duration_min": self._minutes_between(
                    snapshots[0]["timestamp"] if snapshots else now.isoformat(), now.isoformat()
                ),
                "max_score": round(max_score, 4),
            }
        )
        if len(cycles) > 200:
            cycles.pop(0)

    def _compute_profile(self, netuid: Any) -> None:
        cycles = self._cycles[netuid]
        pump_cycles = [c for c in cycles if c.get("max_score", 0) >= 0.5]
        avg_pump_duration = round(mean([c["duration_min"] for c in pump_cycles]), 2) if pump_cycles else 0.0

        consolidations = [
            c for c in cycles
            if c.get("start_phase") == "CONSOLIDATING" and c.get("end_phase") in ("SECOND_WIND", "SELL")
        ]
        avg_consolidation = round(mean([c["duration_min"] for c in consolidations]), 2) if consolidations else 0.0

        re_pump_count = sum(
            1 for c in cycles
            if c.get("start_phase") in ("CONSOLIDATING", "EXHAUSTING") and c.get("end_phase") == "SECOND_WIND"
        )
        re_pump_rate = round(re_pump_count / len(cycles), 4) if cycles else 0.0

        pattern = self._typical_pattern(cycles)

        self._profiles[netuid] = {
            "avg_pump_duration": avg_pump_duration,
            "avg_consolidation_length": avg_consolidation,
            "re_pump_rate": re_pump_rate,
            "typical_pattern": pattern,
            "total_cycles": len(cycles),
        }

    def _typical_pattern(self, cycles: List[Dict[str, Any]]) -> str:
        if len(cycles) < 3:
            return "insufficient_data"
        seqs: Dict[str, int] = defaultdict(int)
        for i in range(len(cycles) - 2):
            key = " -> ".join(cycles[j]["end_phase"] for j in range(i, i + 3))
            seqs[key] += 1
        if not seqs:
            return "mixed"
        return max(seqs, key=seqs.get)

    def _compute_re_pump_prob(self, netuid: Any, pump_score: float, now: datetime) -> float:
        last_pump_time = None
        for s in reversed(self._snapshots[netuid]):
            if s.get("pump_score", 0) >= 0.5:
                last_pump_time = s["timestamp"]
                break
        if last_pump_time is None:
            return 0.0
        hours = self._minutes_between(last_pump_time, now) / 60.0
        return pump_score * math.exp(-0.1 * hours)

    # ------------------------------------------------------------------
    # Outcome feedback
    # ------------------------------------------------------------------
    def record_cycle_outcome(
        self,
        netuid: Any,
        prediction: Any,
        actual: Any,
        phase_at_prediction: Optional[str] = None,
    ) -> None:
        """Update per-phase accuracy from a resolved prediction.

        Accepts either string directions or the dict payloads used by the
        prediction resolver (``predicted_direction`` / ``actual_direction``).
        """
        with self._lock:
            self._ensure_netuid(netuid)
            phase = phase_at_prediction or self._phase_state[netuid].get("phase", "INACTIVE")
            pred_dir = prediction if isinstance(prediction, str) else prediction.get("predicted_direction", "")
            actual_dir = actual if isinstance(actual, str) else actual.get("actual_direction", "")
            bucket = self._accuracy[netuid][phase]
            bucket["total"] += 1
            if pred_dir and actual_dir and pred_dir == actual_dir:
                bucket["correct"] += 1
            self._save_state()

    def update_sentiment(self, netuid: Any, sentiment: float) -> None:
        """No-op compatibility shim; sentiment is not part of this model."""
        self._ensure_netuid(netuid)

    def update_indicators(self, netuid: Any, indicators: Dict[str, Any]) -> None:
        """No-op compatibility shim; indicators feed via record_snapshot."""
        self._ensure_netuid(netuid)

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------
    def get_current_phase(self, netuid: Any) -> str:
        with self._lock:
            self._ensure_netuid(netuid)
            return self._phase_state[netuid].get("phase", "INACTIVE")

    def get_proneness(self, netuid: Any) -> int:
        with self._lock:
            self._ensure_netuid(netuid)
            return int(round(self._last_final_score(netuid) * 100))

    def get_pump_score(self, netuid: Any) -> float:
        with self._lock:
            self._ensure_netuid(netuid)
            return self._last_pump_score(netuid)

    def get_final_score(self, netuid: Any) -> float:
        with self._lock:
            self._ensure_netuid(netuid)
            return self._last_final_score(netuid)

    def get_re_pump_prob(self, netuid: Any) -> float:
        with self._lock:
            self._ensure_netuid(netuid)
            return self._compute_re_pump_prob(netuid, self._last_pump_score(netuid), datetime.now(timezone.utc))

    def get_cycle_context(self, netuid: Any) -> str:
        with self._lock:
            self._ensure_netuid(netuid)
            ps = self._phase_state[netuid]
            return (
                f"phase: {ps.get('phase', 'INACTIVE')} | "
                f"score: {self._last_pump_score(netuid):.2f} | "
                f"final: {self._last_final_score(netuid):.2f} | "
                f"re-pump: {self.get_re_pump_prob(netuid)*100:.0f}% | "
                f"proneness: {self.get_proneness(netuid)}"
            )

    def get_all_analytics(self) -> Dict[str, Any]:
        """Return the full analytics payload used by /api/pump-analytics."""
        with self._lock:
            subnets: List[Dict[str, Any]] = []
            for nid in self._phase_state:
                ps = self._phase_state[nid]
                profile = self._profiles.get(nid, {})
                cusum = self._cusum_state.get(nid, {})
                subnets.append(
                    {
                        "netuid": nid,
                        "name": ps.get("name", f"SN{nid}"),
                        "current_phase": ps.get("phase", "INACTIVE"),
                        "phase_started": ps.get("since"),
                        "phase_duration_minutes": ps.get("duration_min", 0.0),
                        "pump_score": self._last_pump_score(nid),
                        "final_score": self._last_final_score(nid),
                        "pump_proneness": self.get_proneness(nid),
                        "re_pump_prob": round(self.get_re_pump_prob(nid), 4),
                        "cusum": round(cusum.get("cusum", 0.0), 4),
                        "profile": profile,
                        "cycles": self._cycles.get(nid, [])[-10:],
                        "cycle_accuracy": dict(self._accuracy.get(nid, {})),
                    }
                )
            subnets.sort(key=lambda s: s.get("pump_proneness", 0), reverse=True)
            total_cycles = sum(len(v) for v in self._cycles.values())
            avg_proneness = round(mean([s.get("pump_proneness", 0) for s in subnets]), 1) if subnets else 0.0
            return {
                "status": "success",
                "data": {
                    "subnets": subnets,
                    "meta": {
                        "tracked_subnets": len(subnets),
                        "total_cycles": total_cycles,
                        "avg_proneness": avg_proneness,
                        "top_pump_candidates": [s["netuid"] for s in subnets[:5]],
                        "updated_at": self._meta.get("last_updated") or _now_iso(),
                    },
                },
            }

    def get_all_profiles(self) -> Dict[Any, Dict[str, Any]]:
        with self._lock:
            return {nid: dict(self._profiles.get(nid, {})) for nid in self._phase_state}

    def get_current_phases(self) -> Dict[Any, Dict[str, Any]]:
        with self._lock:
            return {
                nid: {
                    "phase": self._phase_state[nid].get("phase", "INACTIVE"),
                    "duration_min": self._phase_state[nid].get("duration_min", 0.0),
                    "since": self._phase_state[nid].get("since"),
                }
                for nid in self._phase_state
            }

    def get_recent_cycles(self, netuid: Optional[Any] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            if netuid is not None:
                return list(reversed(self._cycles.get(netuid, [])[-limit:]))
            all_cycles: List[Dict[str, Any]] = []
            for nid, cycles in self._cycles.items():
                for c in cycles:
                    c = dict(c)
                    c["netuid"] = nid
                    all_cycles.append(c)
            all_cycles.sort(key=lambda c: c.get("end", ""), reverse=True)
            return all_cycles[:limit]

    def get_cycle_analytics_accuracy(self) -> Dict[str, Any]:
        with self._lock:
            merged: Dict[str, Dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
            for nid in self._accuracy:
                for phase, bucket in self._accuracy[nid].items():
                    merged[phase]["correct"] += bucket["correct"]
                    merged[phase]["total"] += bucket["total"]
            summary = {
                phase: {
                    "correct": b["correct"],
                    "total": b["total"],
                    "accuracy": round(b["correct"] / b["total"], 4) if b["total"] else 0.0,
                }
                for phase, b in merged.items()
            }
            return {"status": "success", "accuracy": summary}

    def get_pump_tracker_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": "success",
                "meta": dict(self._meta),
                "phase_state": {str(k): dict(v) for k, v in self._phase_state.items()},
                "cusum_state": {str(k): dict(v) for k, v in self._cusum_state.items()},
                "profiles": {str(k): dict(v) for k, v in self._profiles.items()},
                "snapshot_counts": {str(k): len(v) for k, v in self._snapshots.items()},
                "cycle_counts": {str(k): len(v) for k, v in self._cycles.items()},
            }

    def compute_profile(self, netuid: Any) -> Dict[str, Any]:
        with self._lock:
            self._ensure_netuid(netuid)
            self._compute_profile(netuid)
            return dict(self._profiles.get(netuid, {}))

    def compute_proneness(self, netuid: Any) -> int:
        return self.get_proneness(netuid)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("meta", {}).get("version") != STATE_VERSION:
            # Allow loading if version is close; otherwise start fresh.
            if payload.get("meta", {}).get("version") not in ("2.0", "2.1"):
                return
        self._snapshots = defaultdict(list, {k: list(v) for k, v in payload.get("snapshots", {}).items()})
        self._phase_state = {k: dict(v) for k, v in payload.get("phase_state", {}).items()}
        self._cusum_state = {k: dict(v) for k, v in payload.get("cusum_state", {}).items()}
        self._cycles = defaultdict(list, {k: list(v) for k, v in payload.get("cycles", {}).items()})
        self._profiles = {k: dict(v) for k, v in payload.get("profiles", {}).items()}
        self._accuracy = defaultdict(
            lambda: defaultdict(lambda: {"correct": 0, "total": 0}),
            {
                k: defaultdict(lambda: {"correct": 0, "total": 0}, v)
                for k, v in payload.get("accuracy", {}).items()
            },
        )
        self._meta = dict(payload.get("meta", {"version": STATE_VERSION}))

    def _save_state(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        payload = {
            "meta": self._meta,
            "snapshots": {k: list(v) for k, v in self._snapshots.items()},
            "phase_state": {k: dict(v) for k, v in self._phase_state.items()},
            "cusum_state": {k: dict(v) for k, v in self._cusum_state.items()},
            "cycles": {k: list(v) for k, v in self._cycles.items()},
            "profiles": {k: dict(v) for k, v in self._profiles.items()},
            "accuracy": {k: dict(v) for k, v in self._accuracy.items()},
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, self._path)

    def load_state(self) -> None:
        with self._lock:
            self._load_state()

    def save_state(self) -> None:
        with self._lock:
            self._save_state()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ensure_netuid(self, netuid: Any, name: Optional[str] = None) -> None:
        if netuid not in self._phase_state:
            self._phase_state[netuid] = {
                "phase": "INACTIVE",
                "since": None,
                "duration_min": 0.0,
                "last_transition": None,
                "name": name or f"SN{netuid}",
            }
        if netuid not in self._cusum_state:
            self._cusum_state[netuid] = {"mean": 0.0, "std": 0.0, "cusum_pos": 0.0, "cusum_neg": 0.0, "cusum": 0.0}
        if name and not self._phase_state[netuid].get("name"):
            self._phase_state[netuid]["name"] = name

    def _last_pump_score(self, netuid: Any) -> float:
        if self._snapshots.get(netuid):
            return float(self._snapshots[netuid][-1].get("pump_score", 0.0))
        return 0.0

    def _last_final_score(self, netuid: Any) -> float:
        if self._snapshots.get(netuid):
            return float(self._snapshots[netuid][-1].get("final_score", 0.0))
        return 0.0

    @staticmethod
    def _minutes_between(start: Optional[str], end: Optional[str]) -> float:
        if not start or not end:
            return 0.0
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return max(0.0, (e - s).total_seconds() / 60.0)
        except Exception:
            return 0.0


# ------------------------------------------------------------------------------
# Module-level singleton and exports
# ------------------------------------------------------------------------------
_pump_tracker_instance: Optional[PumpTracker] = None
_pump_tracker_lock = threading.Lock()


def get_pump_tracker(state_path: Optional[str] = None) -> PumpTracker:
    global _pump_tracker_instance
    if _pump_tracker_instance is None:
        with _pump_tracker_lock:
            if _pump_tracker_instance is None:
                _pump_tracker_instance = PumpTracker(state_path=state_path)
    return _pump_tracker_instance


def get_all_profiles() -> Dict[Any, Dict[str, Any]]:
    return get_pump_tracker().get_all_profiles()


def get_current_phases() -> Dict[Any, Dict[str, Any]]:
    return get_pump_tracker().get_current_phases()


def get_recent_cycles(netuid: Optional[Any] = None, limit: int = 20) -> List[Dict[str, Any]]:
    return get_pump_tracker().get_recent_cycles(netuid=netuid, limit=limit)


def get_cycle_analytics_accuracy() -> Dict[str, Any]:
    return get_pump_tracker().get_cycle_analytics_accuracy()


def record_snapshot(
    netuid: Any,
    price: float,
    volume: float,
    buy_volume: float = 0.0,
    sell_volume: float = 0.0,
) -> Dict[str, Any]:
    return get_pump_tracker().record_snapshot(netuid, price, volume, buy_volume, sell_volume)


def get_pump_tracker_state() -> Dict[str, Any]:
    return get_pump_tracker().get_pump_tracker_state()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
