"""
Pump Cycle Tracker - records price movement phases per subnet.

Phases:
  RISING        - price increasing > threshold (3+ consecutive > +0.5% snapshots)
  PEAK          - price stopped rising, within +/-0.5% of local max
  CONSOLIDATING - price flat (3+ snapshots within +/-0.5% of each other)
  DECLINING     - price decreasing > threshold (3+ consecutive < -0.5% snapshots)
  RE_PUMP       - a new RISING phase that starts after CONSOLIDATING or DECLINING

Each subnet accumulates a rolling window of price snapshots (last 50) and a
cycle history. When a full cycle completes
(pump -> consolidation -> optional re-pump -> decline back toward baseline) it is
recorded in the cycles array and the per-subnet behavioral profile is recomputed.

State is persisted to data/pump_cycles.json. The tracker starts empty and
accumulates real data from the first scheduler tick after deploy.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PUMP_CYCLES_PATH = os.environ.get("PUMP_CYCLES_PATH", os.path.join("data", "pump_cycles.json"))

# Tunable phase-detection thresholds.
WINDOW_SIZE = 50              # rolling snapshots kept per subnet
CHANGE_THRESHOLD = 0.5        # % move per snapshot to count as rising/declining
FLAT_THRESHOLD = 0.5          # % band within which price is "flat"
RISING_RUN = 3               # consecutive rising snapshots to confirm RISING
DECLINING_RUN = 3            # consecutive declining snapshots to confirm DECLINING
FLAT_RUN = 3                 # consecutive flat snapshots to confirm CONSOLIDATING
MAX_CYCLES_KEPT = 50         # cap on cycles stored per subnet

PHASE_RISING = "RISING"
PHASE_PEAK = "PEAK"
PHASE_CONSOLIDATING = "CONSOLIDATING"
PHASE_DECLINING = "DECLINING"
PHASE_RE_PUMP = "RE_PUMP"
PHASE_UNKNOWN = "UNKNOWN"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_between(start: str, end: str) -> int:
    s = _parse_dt(start)
    e = _parse_dt(end)
    if not s or not e:
        return 0
    return max(0, int(round((e - s).total_seconds() / 60.0)))


def _empty_state() -> Dict[str, Any]:
    return {
        "snapshots": {},
        "cycles": {},
        "profiles": {},
        "current": {},
        "meta": {
            "created": _now_iso(),
            "last_updated": None,
            "total_snapshots": 0,
        },
    }


class PumpTracker:
    """Tracks per-subnet pump/consolidation/re-pump cycles."""

    def __init__(self, path: str = PUMP_CYCLES_PATH):
        self.path = path
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = _empty_state()
        self.load_state()

    # ------------------------------------------------------------------ state
    def load_state(self) -> Dict[str, Any]:
        with self._lock:
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                    base = _empty_state()
                    base.update(loaded)
                    for key in ("snapshots", "cycles", "profiles", "current"):
                        base.setdefault(key, {})
                    base.setdefault("meta", {})
                    self._state = base
                except Exception as exc:
                    logger.warning("pump_tracker: failed to load %s (%s); starting fresh", self.path, exc)
                    self._state = _empty_state()
            else:
                self._state = _empty_state()
                self.save_state()
            return self._state

    def save_state(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self._state["meta"]["last_updated"] = _now_iso()
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._state, fh, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

    # ----------------------------------------------------------- snapshot I/O
    def record_price_snapshot(
        self, netuid: Any, name: str, price: float, timestamp: Optional[str] = None
    ) -> None:
        """Append a price snapshot for a subnet and re-evaluate its phase."""
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if price <= 0:
            return
        key = str(netuid)
        ts = timestamp or _now_iso()
        with self._lock:
            snaps = self._state["snapshots"].setdefault(key, [])
            snaps.append({"t": ts, "p": price, "name": name})
            if len(snaps) > WINDOW_SIZE:
                del snaps[: len(snaps) - WINDOW_SIZE]
            self._state["current"].setdefault(key, {"netuid": netuid, "name": name})
            self._state["current"][key]["netuid"] = netuid
            self._state["current"][key]["name"] = name
            self._state["meta"]["total_snapshots"] = self._state["meta"].get("total_snapshots", 0) + 1
            self.detect_phase_change(netuid)
            self.save_state()

    # --------------------------------------------------------- phase detection
    def _pct_changes(self, snaps: List[Dict[str, Any]]) -> List[float]:
        changes: List[float] = []
        for i in range(1, len(snaps)):
            prev = snaps[i - 1]["p"]
            cur = snaps[i]["p"]
            if prev > 0:
                changes.append(round((cur - prev) / prev * 100.0, 4))
            else:
                changes.append(0.0)
        return changes

    def _classify_run(self, changes: List[float]) -> str:
        """Classify the most recent run of changes into a phase candidate."""
        if len(changes) < RISING_RUN:
            return PHASE_UNKNOWN
        recent = changes[-RISING_RUN:]
        if all(c > CHANGE_THRESHOLD for c in recent):
            return PHASE_RISING
        if all(c < -CHANGE_THRESHOLD for c in recent):
            return PHASE_DECLINING
        if len(changes) >= FLAT_RUN:
            tail = changes[-FLAT_RUN:]
            if max(tail) - min(tail) <= (2 * FLAT_THRESHOLD):
                return PHASE_CONSOLIDATING
        return PHASE_UNKNOWN

    def detect_phase_change(self, netuid: Any) -> Dict[str, Any]:
        """Compare recent snapshots to detect a phase transition for a subnet."""
        key = str(netuid)
        with self._lock:
            snaps = self._state["snapshots"].get(key, [])
            cur = self._state["current"].get(key, {})
            prev_phase = cur.get("current_phase", PHASE_UNKNOWN)

            if len(snaps) < 2:
                cur["current_phase"] = PHASE_UNKNOWN
                cur["phase_started"] = snaps[-1]["t"] if snaps else _now_iso()
                cur["phase_duration_minutes"] = 0
                self._state["current"][key] = cur
                return cur

            changes = self._pct_changes(snaps)
            candidate = self._classify_run(changes)

            # PEAK detection: middle of the last three snapshots is a local max.
            if len(snaps) >= 3 and prev_phase in (PHASE_RISING, PHASE_RE_PUMP):
                last_three = [snaps[-3]["p"], snaps[-2]["p"], snaps[-1]["p"]]
                if last_three[1] >= last_three[0] and last_three[1] > last_three[2]:
                    candidate = PHASE_PEAK

            # RE_PUMP: a RISING candidate that follows a completed pump phase
            # (CONSOLIDATING / DECLINING / PEAK). Only re-classify as RE_PUMP when
            # a pump cycle already exists for this subnet, so the very first
            # rising sequence is recorded as a normal RISING pump.
            if candidate == PHASE_RISING and prev_phase in (
                PHASE_CONSOLIDATING, PHASE_DECLINING, PHASE_PEAK
            ) and self._state["cycles"].get(key):
                candidate = PHASE_RE_PUMP

            # Inconclusive -> keep previous phase to avoid flapping. The very
            # first snapshots stay UNKNOWN until a clear run emerges.
            if candidate == PHASE_UNKNOWN:
                candidate = prev_phase

            now = _now_iso()
            if candidate != prev_phase:
                self._on_phase_transition(key, prev_phase, candidate, snaps)
                cur["current_phase"] = candidate
                cur["phase_started"] = snaps[-1]["t"]
            else:
                cur["current_phase"] = candidate

            cur["phase_duration_minutes"] = _minutes_between(cur.get("phase_started"), now)
            self._state["current"][key] = cur
            return cur

    # ----------------------------------------------------- cycle bookkeeping
    def _on_phase_transition(
        self, key: str, prev_phase: str, new_phase: str, snaps: List[Dict[str, Any]]
    ) -> None:
        """Update the in-progress cycle record on each phase transition."""
        cycles: List[Dict[str, Any]] = self._state["cycles"].setdefault(key, [])
        now_t = snaps[-1]["t"] if snaps else _now_iso()

        if new_phase in (PHASE_RISING, PHASE_RE_PUMP) and prev_phase in (
            PHASE_UNKNOWN, PHASE_CONSOLIDATING, PHASE_DECLINING, PHASE_PEAK, None
        ):
            if new_phase == PHASE_RISING:
                cycles.append({
                    "cycle_id": len(cycles) + 1,
                    "pump_start": now_t,
                    "pump_peak": None,
                    "pump_duration_minutes": 0,
                    "pump_magnitude_pct": 0.0,
                    "consolidation_start": None,
                    "consolidation_duration_minutes": 0,
                    "consolidation_depth_pct": 0.0,
                    "re_pump": False,
                    "re_pump_start": None,
                    "re_pump_duration_minutes": 0,
                    "re_pump_magnitude_pct": 0.0,
                    "completed": False,
                })
            else:  # RE_PUMP - extend the most recent open cycle.
                if cycles and not cycles[-1].get("completed"):
                    cycles[-1]["re_pump"] = True
                    cycles[-1]["re_pump_start"] = now_t
            return

        if not cycles or cycles[-1].get("completed"):
            return
        cycle = cycles[-1]

        if new_phase == PHASE_PEAK and prev_phase in (PHASE_RISING, PHASE_RE_PUMP):
            cycle["pump_peak"] = now_t
            if cycle.get("pump_start"):
                cycle["pump_duration_minutes"] = _minutes_between(cycle["pump_start"], now_t)
            start_p = self._price_at(snaps, cycle.get("pump_start"))
            peak_p = self._price_at(snaps, now_t)
            if start_p and peak_p:
                cycle["pump_magnitude_pct"] = round((peak_p - start_p) / start_p * 100.0, 2)

        elif new_phase == PHASE_CONSOLIDATING:
            if not cycle.get("consolidation_start"):
                cycle["consolidation_start"] = now_t

        elif new_phase == PHASE_DECLINING:
            if cycle.get("consolidation_start"):
                cycle["consolidation_duration_minutes"] = _minutes_between(
                    cycle["consolidation_start"], now_t
                )
                cons_p = self._price_at(snaps, cycle["consolidation_start"])
                end_p = self._price_at(snaps, now_t)
                if cons_p and end_p:
                    cycle["consolidation_depth_pct"] = round((end_p - cons_p) / cons_p * 100.0, 2)
            if cycle.get("re_pump_start"):
                cycle["re_pump_duration_minutes"] = _minutes_between(cycle["re_pump_start"], now_t)
                rp_p = self._price_at(snaps, cycle["re_pump_start"])
                end_p = self._price_at(snaps, now_t)
                if rp_p and end_p:
                    cycle["re_pump_magnitude_pct"] = round((end_p - rp_p) / rp_p * 100.0, 2)
            cycle["completed"] = True
            cycle["completed_at"] = now_t
            self._trim_cycles(key)
            self.compute_profile(netuid=key)

    def _price_at(self, snaps: List[Dict[str, Any]], ts: Optional[str]) -> Optional[float]:
        if not ts:
            return None
        target = _parse_dt(ts)
        if not target:
            return None
        best = None
        best_delta = None
        for s in snaps:
            d = _parse_dt(s.get("t"))
            if not d:
                continue
            delta = abs((d - target).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = s.get("p")
        return best

    def _trim_cycles(self, key: str) -> None:
        cycles = self._state["cycles"].get(key, [])
        if len(cycles) > MAX_CYCLES_KEPT:
            self._state["cycles"][key] = cycles[-MAX_CYCLES_KEPT:]

    # --------------------------------------------------------------- profiles
    def compute_profile(self, netuid: Any) -> Dict[str, Any]:
        key = str(netuid)
        with self._lock:
            cycles = [c for c in self._state["cycles"].get(key, []) if c.get("completed")]
            if not cycles:
                profile = {
                    "avg_pump_duration": 0,
                    "avg_consolidation_duration": 0,
                    "re_pump_rate": 0.0,
                    "avg_re_pump_magnitude": 0.0,
                    "total_cycles_observed": 0,
                    "typical_pattern": "insufficient data",
                }
                self._state["profiles"][key] = profile
                return profile

            pump_durs = [c.get("pump_duration_minutes", 0) for c in cycles]
            cons_durs = [c.get("consolidation_duration_minutes", 0) for c in cycles]
            re_pumps = [c for c in cycles if c.get("re_pump")]
            re_mags = [c.get("re_pump_magnitude_pct", 0) for c in re_pumps]

            avg_pump = round(sum(pump_durs) / len(pump_durs)) if pump_durs else 0
            avg_cons = round(sum(cons_durs) / len(cons_durs)) if cons_durs else 0
            re_rate = round(len(re_pumps) / len(cycles), 2) if cycles else 0.0
            avg_re_mag = round(sum(re_mags) / len(re_mags), 2) if re_mags else 0.0

            def _h(minutes: int) -> str:
                if minutes <= 0:
                    return "0min"
                h, m = divmod(minutes, 60)
                if h and m:
                    return f"{h}h{m}m"
                return f"{h}h" if h else f"{m}min"

            pattern = f"pump_{_h(avg_pump)} -> consolidate_{_h(avg_cons)}"
            if re_rate > 0 and re_pumps:
                avg_re_dur = round(sum(c.get("re_pump_duration_minutes", 0) for c in re_pumps) / len(re_pumps))
                pattern += f" -> re_pump_{_h(avg_re_dur)}"

            profile = {
                "avg_pump_duration": avg_pump,
                "avg_consolidation_duration": avg_cons,
                "re_pump_rate": re_rate,
                "avg_re_pump_magnitude": avg_re_mag,
                "total_cycles_observed": len(cycles),
                "typical_pattern": pattern,
            }
            self._state["profiles"][key] = profile
            return profile

    # --------------------------------------------------------------- accessors
    def get_current_phase(self, netuid: Any) -> Dict[str, Any]:
        key = str(netuid)
        with self._lock:
            cur = self._state["current"].get(key)
            if not cur:
                return {"netuid": netuid, "current_phase": PHASE_UNKNOWN, "phase_duration_minutes": 0}
            return {
                "netuid": cur.get("netuid", netuid),
                "name": cur.get("name", ""),
                "current_phase": cur.get("current_phase", PHASE_UNKNOWN),
                "phase_started": cur.get("phase_started"),
                "phase_duration_minutes": cur.get("phase_duration_minutes", 0),
            }

    def get_profile(self, netuid: Any) -> Dict[str, Any]:
        key = str(netuid)
        with self._lock:
            return self._state["profiles"].get(key) or self.compute_profile(netuid)

    def get_recent_cycles(self, netuid: Any, limit: int = 5) -> List[Dict[str, Any]]:
        key = str(netuid)
        with self._lock:
            cycles = list(self._state["cycles"].get(key, []))
            return cycles[-limit:]

    def get_all_profiles(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state["profiles"])

    def get_subnet_view(self, netuid: Any) -> Dict[str, Any]:
        cur = self.get_current_phase(netuid)
        return {
            "netuid": cur.get("netuid", netuid),
            "name": cur.get("name", ""),
            "current_phase": cur.get("current_phase", PHASE_UNKNOWN),
            "phase_duration_minutes": cur.get("phase_duration_minutes", 0),
            "profile": self.get_profile(netuid),
            "recent_cycles": self.get_recent_cycles(netuid, 5),
        }

    def get_analytics(self, netuid: Optional[Any] = None) -> Dict[str, Any]:
        """Return the full analytics payload (optionally filtered by netuid)."""
        with self._lock:
            if netuid is not None:
                return {"subnets": [self.get_subnet_view(netuid)], "meta": self._meta(True)}

            subnets: List[Dict[str, Any]] = []
            for key in self._state["current"].keys():
                subnets.append(self.get_subnet_view(key))
            seen = {str(s.get("netuid")) for s in subnets}
            for key, prof in self._state["profiles"].items():
                if key in seen:
                    continue
                subnets.append({
                    "netuid": key,
                    "name": "",
                    "current_phase": PHASE_UNKNOWN,
                    "phase_duration_minutes": 0,
                    "profile": prof,
                    "recent_cycles": self.get_recent_cycles(key, 5),
                })
            return {"subnets": subnets, "meta": self._meta(False)}

    def _meta(self, filtered: bool) -> Dict[str, Any]:
        with self._lock:
            total_cycles = sum(len(v) for v in self._state["cycles"].values())
            return {
                "tracked_subnets": len(self._state["current"]),
                "total_cycles": total_cycles,
                "updated_at": self._state["meta"].get("last_updated"),
                "filtered": filtered,
            }

    # ------------------------------------------- learning-loop cycle context
    def build_cycle_context(
        self,
        netuid: Any,
        phase_at_prediction: Optional[str] = None,
        phase_duration_at_prediction: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build the cycle_context block attached to a resolved prediction."""
        cur = self.get_current_phase(netuid)
        profile = self.get_profile(netuid)
        re_pump_expected = profile.get("re_pump_rate", 0.0) >= 0.4
        return {
            "phase_at_prediction": phase_at_prediction or PHASE_UNKNOWN,
            "phase_at_resolution": cur.get("current_phase", PHASE_UNKNOWN),
            "phase_duration_at_prediction": int(phase_duration_at_prediction or 0),
            "profile_predicted_re_pump": bool(re_pump_expected),
            "cycle_outcome": self._cycle_outcome(
                phase_at_prediction, cur.get("current_phase", PHASE_UNKNOWN)
            ),
        }

    @staticmethod
    def _cycle_outcome(at_pred: Optional[str], at_res: str) -> str:
        if not at_pred:
            return "unknown"
        if at_pred in (PHASE_RISING, PHASE_RE_PUMP) and at_res in (PHASE_PEAK, PHASE_CONSOLIDATING, PHASE_DECLINING):
            return "pump_completed_before_prediction_window"
        if at_pred == PHASE_CONSOLIDATING and at_res in (PHASE_RISING, PHASE_RE_PUMP):
            return "re_pump_within_prediction_window"
        if at_pred == PHASE_DECLINING and at_res in (PHASE_RISING, PHASE_RE_PUMP):
            return "reversal_within_prediction_window"
        return "phase_held_through_prediction_window"


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


def record_price_snapshot(netuid: Any, name: str, price: float, timestamp: Optional[str] = None) -> None:
    try:
        get_pump_tracker().record_price_snapshot(netuid, name, price, timestamp)
    except Exception as exc:
        logger.warning("pump_tracker record_price_snapshot failed: %s", exc)


def detect_phase_change(netuid: Any) -> Dict[str, Any]:
    return get_pump_tracker().detect_phase_change(netuid)


def compute_profile(netuid: Any) -> Dict[str, Any]:
    return get_pump_tracker().compute_profile(netuid)


def get_current_phase(netuid: Any) -> Dict[str, Any]:
    return get_pump_tracker().get_current_phase(netuid)


def get_all_profiles() -> Dict[str, Any]:
    return get_pump_tracker().get_all_profiles()


def get_analytics(netuid: Optional[Any] = None) -> Dict[str, Any]:
    return get_pump_tracker().get_analytics(netuid)


def build_cycle_context(
    netuid: Any,
    phase_at_prediction: Optional[str] = None,
    phase_duration_at_prediction: Optional[int] = None,
) -> Dict[str, Any]:
    return get_pump_tracker().build_cycle_context(
        netuid, phase_at_prediction, phase_duration_at_prediction
    )
