"""
Prediction Store — persistent storage for the self-learning loop.

Every prediction is framed as "predicted to move +X% within N hours" and
flows through the closed loop:

    prediction (stored) -> outcome_resolver (resolve) ->
    adversarial judge (judge) -> weights (update) -> better picks

Backed by data/predictions.json (a JSON object with `predictions` and
`resolved` arrays). Capped at MAX_PREDICTIONS entries via FIFO eviction so
the store stays bounded across restarts.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_PREDICTIONS = 1000

_DEFAULT_PATH = os.path.join("data", "predictions.json")

# Module-level lock so the background learner and request handlers never
# corrupt the JSON file with interleaved writes.
_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


class PredictionStore:
    """Persistent prediction storage with FIFO eviction."""

    def __init__(self, path: str = _DEFAULT_PATH, max_predictions: int = MAX_PREDICTIONS):
        self.path = path
        self.max_predictions = max_predictions
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    # ------------------------------------------------------------------
    # Low-level persistence
    # ------------------------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._empty()
            data.setdefault("predictions", [])
            data.setdefault("resolved", [])
            data.setdefault("stats", {})
            return data
        except Exception:
            return self._empty()

    def _empty(self) -> Dict[str, Any]:
        return {"predictions": [], "resolved": [], "stats": {}}

    def _save(self, data: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            # Last-resort direct write if atomic replace fails (e.g. cross-device).
            try:
                with open(self.path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

    def _recompute_stats(self, data: Dict[str, Any]) -> None:
        preds = data.get("predictions", [])
        resolved = data.get("resolved", [])
        correct = sum(1 for r in resolved if r.get("outcome") == "correct")
        partial = sum(1 for r in resolved if r.get("outcome") == "partial")
        wrong = sum(1 for r in resolved if r.get("outcome") == "wrong")
        expired = sum(1 for r in resolved if r.get("outcome") == "expired")
        judged = correct + partial + wrong
        accuracy = round(correct / judged, 4) if judged else 0.0
        data["stats"] = {
            "pending": len(preds),
            "resolved": len(resolved),
            "correct": correct,
            "partial": partial,
            "wrong": wrong,
            "expired": expired,
            "total": len(preds) + len(resolved),
            "accuracy": accuracy,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_prediction(self, prediction: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new prediction, enforcing the FIFO cap."""
        with _LOCK:
            data = self._load()
            preds = data.setdefault("predictions", [])

            entry = {
                "id": prediction.get("id") or ("pred_" + uuid.uuid4().hex[:10]),
                "subnet": prediction.get("subnet") or prediction.get("name"),
                "netuid": prediction.get("netuid"),
                "direction": prediction.get("direction", "up"),
                "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
                "horizon_hours": int(prediction.get("horizon_hours", 24) or 24),
                "reference_price": float(prediction.get("reference_price", 0) or 0),
                "reference_time": prediction.get("reference_time") or _now_iso(),
                "due_time": prediction.get("due_time") or prediction.get("resolve_at") or _now_iso(),
                "status": "pending",
                "conviction": int(prediction.get("conviction", 50) or 50),
                "experts_involved": list(prediction.get("experts_involved", []) or []),
                "reasons": list(prediction.get("reasons", []) or []),
                "signal_tags": list(prediction.get("signal_tags", []) or []),
                "signal_source": prediction.get("signal_source"),
                "statement": prediction.get("statement"),
                "resolution": None,
                "outcome": None,
            }
            # Carry forward legacy fields used elsewhere in the codebase.
            for legacy in ("name", "created_at", "resolve_at"):
                if legacy in prediction:
                    entry[legacy] = prediction[legacy]
            if "created_at" not in entry:
                entry["created_at"] = entry["reference_time"]
            if "resolve_at" not in entry:
                entry["resolve_at"] = entry["due_time"]

            preds.append(entry)
            # FIFO eviction across both pending + resolved buckets.
            self._evict(data)
            self._recompute_stats(data)
            self._save(data)
            return entry

    def _evict(self, data: Dict[str, Any]) -> None:
        preds = data.get("predictions", [])
        resolved = data.get("resolved", [])
        overflow = (len(preds) + len(resolved)) - self.max_predictions
        while overflow > 0 and (preds or resolved):
            if resolved:
                resolved.pop(0)
            elif preds:
                preds.pop(0)
            overflow -= 1

    def get_pending(self) -> List[Dict[str, Any]]:
        return list(self._load().get("predictions", []))

    def get_resolved(self) -> List[Dict[str, Any]]:
        return list(self._load().get("resolved", []))

    def get_due(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Return pending predictions whose due_time has elapsed."""
        now = now or datetime.now(timezone.utc)
        due = []
        for p in self._load().get("predictions", []):
            due_dt = _parse_iso(p.get("due_time") or p.get("resolve_at"))
            if due_dt and due_dt <= now:
                due.append(p)
        return due

    def resolve(
        self,
        prediction_id: str,
        resolution: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Move a pending prediction to resolved with its resolution payload."""
        with _LOCK:
            data = self._load()
            preds = data.get("predictions", [])
            resolved = data.get("resolved", [])
            target = None
            for i, p in enumerate(preds):
                if p.get("id") == prediction_id:
                    target = preds.pop(i)
                    break
            if target is None:
                # Already resolved? update in place.
                for r in resolved:
                    if r.get("id") == prediction_id:
                        r.update(resolution)
                        self._recompute_stats(data)
                        self._save(data)
                        return r
                return None
            target["status"] = "resolved"
            target["resolution"] = resolution
            target["outcome"] = resolution.get("outcome")
            target["resolved_at"] = resolution.get("resolved_at") or _now_iso()
            resolved.append(target)
            self._evict(data)
            self._recompute_stats(data)
            self._save(data)
            return target

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Most recent resolved predictions (newest last)."""
        resolved = self._load().get("resolved", [])
        return resolved[-limit:]

    def get_cemetery(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Wrong (false-positive) predictions — the learning cemetery."""
        wrong = [
            r for r in self._load().get("resolved", [])
            if r.get("outcome") == "wrong"
        ]
        return wrong[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        data = self._load()
        self._recompute_stats(data)
        return data.get("stats", {})

    def all(self) -> Dict[str, Any]:
        """Return the full store snapshot (predictions + resolved + stats)."""
        with _LOCK:
            data = self._load()
            self._recompute_stats(data)
            return {
                "predictions": data.get("predictions", []),
                "resolved": data.get("resolved", []),
                "stats": data.get("stats", {}),
            }


# Module-level singleton used by server.py and the learner.
PREDICTION_STORE = PredictionStore()
