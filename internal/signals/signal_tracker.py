"""
Signal/pump-cycle timing tracker.

Tracks the lifecycle of attention signals for assets:
1. first-signal-to-pump latency
2. pump duration
3. asset resurge timing after first pump

Supported sources: news, x, discord, telegram.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

SIGNAL_SOURCES = {"news", "x", "discord", "telegram"}

# Pump detection parameters (tunable via environment variables).
PUMP_START_MIN_SOURCES = int(os.environ.get("PUMP_START_MIN_SOURCES", "2"))
PUMP_START_WINDOW_SECONDS = int(os.environ.get("PUMP_START_WINDOW_SECONDS", "21600"))  # 6h
PUMP_END_IDLE_SECONDS = int(os.environ.get("PUMP_END_IDLE_SECONDS", "7200"))  # 2h
RESURGENCE_IDLE_SECONDS = int(os.environ.get("RESURGENCE_IDLE_SECONDS", "21600"))  # 6h

DEFAULT_PERSISTENCE_PATH = os.environ.get("SIGNAL_TIMELINE_PATH", "data/signal_timeline.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class SignalTracker:
    """
    Persistent tracker for asset signal/pump lifecycle.

    State machine:
        idle -> pumping (pump start criteria met)
        pumping -> pumped (no new signal for PUMP_END_IDLE_SECONDS)
        pumped -> resurging (new signal after RESURGENCE_IDLE_SECONDS)
    """

    def __init__(self, persistence_path: str = DEFAULT_PERSISTENCE_PATH):
        self.persistence_path = persistence_path
        self._state: Dict[str, Any] = {"updated_at": None, "assets": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.persistence_path):
            try:
                with open(self.persistence_path, "r") as f:
                    data = json.load(f)
                self._state["updated_at"] = data.get("updated_at")
                self._state["assets"] = data.get("assets", {})
            except Exception:
                self._state = {"updated_at": None, "assets": {}}

    def _save(self):
        dir_name = os.path.dirname(self.persistence_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        self._state["updated_at"] = _now_iso()
        try:
            with open(self.persistence_path, "w") as f:
                json.dump(self._state, f, indent=2)
        except Exception:
            pass

    def record_signal(
        self,
        asset: str,
        source: str,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a new signal for an asset and update its pump-cycle state.

        Args:
            asset: Asset symbol/name (e.g. "TAO").
            source: One of news, x, discord, telegram.
            timestamp: ISO-8601 timestamp; defaults to now.
            metadata: Optional signal metadata (e.g. mention count, url).

        Returns:
            The enriched asset timeline record.
        """
        asset = asset.upper().strip()
        source = source.lower().strip()
        if source not in SIGNAL_SOURCES:
            raise ValueError(f"Unsupported source: {source}. Use one of {SIGNAL_SOURCES}")

        now = _parse_iso(timestamp) or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        assets = self._state.setdefault("assets", {})
        record = assets.setdefault(
            asset,
            {
                "first_signal_at": None,
                "first_signal_source": None,
                "pump_started_at": None,
                "pump_ended_at": None,
                "resurgence_at": None,
                "sources": [],
                "signal_count": 0,
                "signals": [],
                "state": "idle",
            },
        )

        if record["first_signal_at"] is None:
            record["first_signal_at"] = now_iso
            record["first_signal_source"] = source

        record["signals"].append(
            {"source": source, "timestamp": now_iso, "metadata": metadata or {}}
        )
        record["signal_count"] += 1
        if source not in record["sources"]:
            record["sources"].append(source)

        self._update_state(record, now)
        self._save()
        return self._enrich(record)

    def _update_state(self, record: Dict[str, Any], now: datetime):
        state = record.get("state", "idle")
        signals = record.get("signals", [])

        if state == "idle":
            if self._should_start_pump(record, now):
                record["pump_started_at"] = now.isoformat()
                record["state"] = "pumping"
            return

        if not signals:
            return

        current_signal = _parse_iso(signals[-1]["timestamp"]) or now

        if state == "pumping":
            if len(signals) >= 2:
                prev_signal = _parse_iso(signals[-2]["timestamp"])
                if prev_signal:
                    gap_seconds = (current_signal - prev_signal).total_seconds()
                    if gap_seconds > PUMP_END_IDLE_SECONDS:
                        record["pump_ended_at"] = prev_signal.isoformat()
                        if gap_seconds > RESURGENCE_IDLE_SECONDS:
                            record["resurgence_at"] = current_signal.isoformat()
                            record["state"] = "resurging"
                        else:
                            record["state"] = "pumped"
        elif state == "pumped":
            pump_ended_at = _parse_iso(record.get("pump_ended_at"))
            if pump_ended_at:
                gap_seconds = (current_signal - pump_ended_at).total_seconds()
                if gap_seconds > RESURGENCE_IDLE_SECONDS:
                    record["resurgence_at"] = current_signal.isoformat()
                    record["state"] = "resurging"

    def _should_start_pump(self, record: Dict[str, Any], now: datetime) -> bool:
        first_signal_at = _parse_iso(record.get("first_signal_at"))
        if not first_signal_at:
            return False
        signals = record.get("signals", [])
        window_start = now - timedelta(seconds=PUMP_START_WINDOW_SECONDS)
        recent = [
            s
            for s in signals
            if (_parse_iso(s["timestamp"]) or now) >= window_start
        ]
        recent_sources = {s["source"] for s in recent}
        return (
            len(recent_sources) >= PUMP_START_MIN_SOURCES
            and len(recent) >= PUMP_START_MIN_SOURCES
        )

    def _compute_metrics(self, record: Dict[str, Any]) -> Dict[str, Any]:
        first = _parse_iso(record.get("first_signal_at"))
        start = _parse_iso(record.get("pump_started_at"))
        end = _parse_iso(record.get("pump_ended_at"))
        resurge = _parse_iso(record.get("resurgence_at"))

        metrics = {
            "time_to_pump_seconds": None,
            "pump_duration_seconds": None,
            "time_to_resurgence_seconds": None,
            "signal_count": record.get("signal_count", 0),
            "distinct_sources": len(record.get("sources", [])),
        }
        if first and start:
            metrics["time_to_pump_seconds"] = int((start - first).total_seconds())
        if start and end:
            metrics["pump_duration_seconds"] = int((end - start).total_seconds())
        if end and resurge:
            metrics["time_to_resurgence_seconds"] = int((resurge - end).total_seconds())
        return metrics

    def _enrich(self, record: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(record)
        enriched["metrics"] = self._compute_metrics(record)
        return enriched

    def get_timeline(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """Return the full timeline or a single asset's timeline."""
        if asset:
            asset = asset.upper().strip()
            record = self._state.get("assets", {}).get(asset)
            if not record:
                return {"asset": asset, "found": False, "data": None}
            return {"asset": asset, "found": True, "data": self._enrich(record)}
        return {
            "updated_at": self._state.get("updated_at"),
            "assets": {
                k: self._enrich(v) for k, v in self._state.get("assets", {}).items()
            },
        }

    def reset_asset(self, asset: str) -> Dict[str, Any]:
        """Reset a single asset's timeline (useful for testing)."""
        asset = asset.upper().strip()
        if asset in self._state.get("assets", {}):
            del self._state["assets"][asset]
            self._save()
        return {"asset": asset, "reset": True}

    def ingest_intelligence(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Ingest a structured intelligence payload.

        Accepts either a single signal object or an object with a "signals" list.
        Each signal must contain at least "asset" and "source".
        """
        results = []
        signals = payload if isinstance(payload, list) else payload.get("signals", [payload])
        for signal in signals:
            if not signal:
                continue
            try:
                result = self.record_signal(
                    asset=signal.get("asset", ""),
                    source=signal.get("source", ""),
                    timestamp=signal.get("timestamp"),
                    metadata=signal.get("metadata"),
                )
                results.append(
                    {"ok": True, "asset": signal.get("asset", "").upper(), "data": result}
                )
            except Exception as e:
                results.append(
                    {"ok": False, "asset": signal.get("asset", "").upper(), "error": str(e)}
                )
        return results
