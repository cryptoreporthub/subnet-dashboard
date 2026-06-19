"""
Poller Signal Worker (The Worker)

Responsible for raw data ingestion via polling within the hierarchical,
Mindmap-integrated Engine.
"""

import json
import os
from typing import Any, Dict, List, Optional

from internal.signals.signal_tracker import SignalTracker


class PollerWorker:
    """Polls configured signal sources and records them in the pump-cycle tracker."""

    def __init__(self, tracker: SignalTracker = None):
        self.tracker = tracker or SignalTracker()

    def poll(self, asset: str, source: str, timestamp: str = None, metadata: dict = None) -> dict:
        """
        Poll a signal source and record a signal for the asset.

        In a production deployment this would connect to the actual source feed;
        for now it normalizes the incoming signal and persists it through the
        SignalTracker so the pump-cycle state machine can advance.
        """
        return self.tracker.record_signal(asset, source, timestamp, metadata)


# ---------------------------------------------------------------------------
# Learning Trail builder (SimiVision adversarial intelligence surface)
# ---------------------------------------------------------------------------

SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
VERDICTS_JSONL_PATH = os.environ.get("VERDICTS_JSONL_PATH", "data/verdicts.jsonl")
REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "60"))


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
    return rows


def _verdicts_jsonl_path(soul_map_path: str = SOUL_MAP_PATH) -> str:
    """Return a verdicts.jsonl path sibling to the given soul_map.json."""
    base, _ = os.path.splitext(soul_map_path)
    return base + "_verdicts.jsonl"


def _mirror_verdicts_to_jsonl(
    soul_map_path: str = SOUL_MAP_PATH,
    verdicts_path: str = None,
) -> str:
    """
    Mirror the adversarial verdicts stored in the Soul-Map into a JSONL file.
    Returns the path used.
    """
    verdicts_path = verdicts_path or _verdicts_jsonl_path(soul_map_path)
    soul_map = _load_json(soul_map_path)
    verdicts = soul_map.get("adversarial_state", {}).get("verdicts", [])

    dir_name = os.path.dirname(verdicts_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)

    temp_path = verdicts_path + ".tmp"
    with open(temp_path, "w") as f:
        for verdict in verdicts:
            f.write(json.dumps(verdict) + "\n")
    os.replace(temp_path, verdicts_path)
    return verdicts_path


def build_learning_trail(
    soul_map_path: str = SOUL_MAP_PATH,
    verdicts_path: str = None,
    refresh_minutes: int = None,
) -> Dict[str, Any]:
    """
    Build the SimiVision Learning Trail payload from the Soul-Map and the
    persisted verdicts JSONL stream.

    Returns:
        {
            experts: [
                {
                    name: str,
                    weight: float,
                    track_record: { correct, total, accuracy },
                    confidence: float,
                    last_verdict: str | None,
                }
            ],
            verdicts: [
                {
                    time: str,
                    subnet_uid: int | None,
                    prediction: str,
                    actual_outcome: str,
                    expert_verdicts: { name: score },
                    confident: bool,
                }
            ],
            refresh_minutes: int,
        }
    """
    # Keep the JSONL mirror in sync with the Soul-Map so the UI/API always
    # reads a consistent trail even if the scheduler has not yet flushed.
    # Only overwrite the JSONL if the Soul-Map actually contains verdicts;
    # otherwise trust the existing JSONL stream (e.g. tests or live writes).
    soul_map = _load_json(soul_map_path)
    soul_verdicts = soul_map.get("adversarial_state", {}).get("verdicts", [])
    if soul_verdicts:
        verdicts_path = verdicts_path or _verdicts_jsonl_path(soul_map_path)
        _mirror_verdicts_to_jsonl(soul_map_path, verdicts_path)

    verdicts_path = verdicts_path or VERDICTS_JSONL_PATH

    adversarial_state = soul_map.get("adversarial_state", {})

    weights = adversarial_state.get("council_weights", {})
    records = adversarial_state.get("expert_track_records", {})
    verdicts = _load_jsonl(verdicts_path)

    expert_names = ("quant", "hype", "contrarian")
    experts: List[Dict[str, Any]] = []
    for name in expert_names:
        record = records.get(name, {})
        total = record.get("total", 0)
        correct = record.get("correct", 0.0)
        accuracy = record.get("accuracy", 0.5)
        # last verdict timestamp where this expert contributed
        last_verdict = None
        for v in reversed(verdicts):
            if name in v.get("expert_contributions", {}):
                last_verdict = v.get("timestamp")
                break
        experts.append(
            {
                "name": name,
                "weight": weights.get(name, 0.33),
                "track_record": {
                    "correct": correct,
                    "total": total,
                    "accuracy": accuracy,
                },
                "confidence": accuracy,
                "last_verdict": last_verdict,
            }
        )

    shaped_verdicts: List[Dict[str, Any]] = []
    for v in verdicts:
        contributions = v.get("expert_contributions", {})
        shaped_verdicts.append(
            {
                "time": v.get("timestamp"),
                "subnet_uid": v.get("subnet_id"),
                "prediction": v.get("action", "hold"),
                "actual_outcome": v.get("outcome_label", "neutral"),
                "expert_verdicts": {
                    name: contributions.get(name, {}).get("score", 0.5)
                    for name in expert_names
                },
                "confident": (v.get("confidence", 0.0) or 0.0) >= 0.7,
            }
        )

    return {
        "experts": experts,
        "verdicts": shaped_verdicts,
        "refresh_minutes": refresh_minutes or REFRESH_MINUTES,
    }
