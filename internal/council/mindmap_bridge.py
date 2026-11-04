"""
Mindmap Bridge (The Connector)

Provides a read/write interface for the Soul-Map within the hierarchical,
Mindmap-integrated Engine.
"""

import itertools
import logging
import os
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.store.soul_map_io import read_soul_map, write_soul_map_committed

logger = logging.getLogger(__name__)

# Mirror CYCLE_HISTORY_MAX=10 / learning_trail[-200:] — memory-only heal; on-disk
# shrink is the compaction operation (Runbook v4), not this constant alone.
FEEDBACK_LOGS_MAX = 10

# Trail rows whose disk write failed, per soul-map path (abspath). Process-local, shared by
# every bridge, because callers such as trail_events build a fresh bridge per event. A row
# leaves the buffer only after a write that carried it commits. Capped, so a long outage
# cannot grow memory without bound; overflow drops the oldest rows and logs the count.
_PENDING_TRAIL_MAX = 50
_PENDING_TRAIL: Dict[str, List[Tuple[int, Dict[str, Any], Any]]] = {}
_PENDING_TRAIL_LOCK = threading.Lock()
_PENDING_SEQ = itertools.count(1)


def _pending_key(persistence_path: str) -> str:
    return os.path.abspath(persistence_path)


def _enqueue_pending(key: str, entry: Dict[str, Any], resolved_prediction_id: Any) -> None:
    with _PENDING_TRAIL_LOCK:
        rows = _PENDING_TRAIL.setdefault(key, [])
        rows.append((next(_PENDING_SEQ), entry, resolved_prediction_id))
        dropped = len(rows) - _PENDING_TRAIL_MAX
        if dropped > 0:
            del rows[:dropped]
            logger.warning(
                "soul_map pending trail buffer over cap path=%s dropped=%d", key, dropped
            )


def _snapshot_pending(key: str) -> Tuple[int, List[Tuple[Dict[str, Any], Any]]]:
    """Return (highest seq in the buffer, rows) for `key`. The seq bounds what a commit covers."""
    with _PENDING_TRAIL_LOCK:
        rows = _PENDING_TRAIL.get(key, [])
        if not rows:
            return 0, []
        return rows[-1][0], [(entry, rid) for _, entry, rid in rows]


def _drop_pending_through(key: str, seq: int) -> None:
    """Drop rows a committed write carried. Rows appended after that write stay buffered."""
    with _PENDING_TRAIL_LOCK:
        rows = _PENDING_TRAIL.get(key)
        if rows is None:
            return
        remaining = [row for row in rows if row[0] > seq]
        if remaining:
            _PENDING_TRAIL[key] = remaining
        else:
            del _PENDING_TRAIL[key]


def pending_resolved_ids(persistence_path: str) -> List[Any]:
    """Resolved prediction ids whose rows are buffered (not yet on disk) for this path."""
    with _PENDING_TRAIL_LOCK:
        return [rid for _, _, rid in _PENDING_TRAIL.get(_pending_key(persistence_path), []) if rid is not None]


def _trail_key(entry: Any) -> Optional[Tuple[str, str]]:
    """Identity of a trail row. Rows without a time cannot be matched, so they are never skipped."""
    if isinstance(entry, dict) and entry.get("time") is not None:
        return str(entry.get("event_type")), str(entry["time"])
    return None


def _replay_trail_rows(state: Dict[str, Any], rows: List[Tuple[Dict[str, Any], Any]]) -> None:
    """Apply learning-trail rows and their resolved ids to a soul_map_state dict in order.

    Idempotent: a row whose (event_type, time) is already in the trail is skipped, ledger id
    included. The same buffered row is replayed by every write until one commits, so it can
    arrive more than once.
    """
    if not rows:
        return
    trail = state.get("learning_trail")
    if not isinstance(trail, list):
        trail = []
    present = {key for key in map(_trail_key, trail) if key is not None}
    for entry, resolved_prediction_id in rows:
        key = _trail_key(entry)
        if key is not None:
            if key in present:
                continue
            present.add(key)
        if resolved_prediction_id is not None:
            ledger = state.get("resolved_prediction_ids")
            if not isinstance(ledger, list):
                ledger = []
                state["resolved_prediction_ids"] = ledger
            if resolved_prediction_id not in ledger:
                ledger.append(resolved_prediction_id)
        trail.append(entry)
    state["learning_trail"] = trail[-200:]


class MindmapBridge:
    def __init__(self, persistence_path: str = "data/soul_map.json", registry_path: str = "config/registry.json"):
        self.persistence_path = persistence_path
        self.registry_path = registry_path
        self.soul_map_state: Dict[str, Any] = {}
        self.feedback_logs: list = []
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            data = read_soul_map(self.persistence_path)
            self.soul_map_state = data.get("soul_map_state", {})
            logs = data.get("feedback_logs", [])
            if isinstance(logs, list):
                self.feedback_logs = logs[-FEEDBACK_LOGS_MAX:]
            else:
                # Non-list payload: preserve as empty list in memory (safe); do not
                # rewrite disk here — compaction owns on-disk shape.
                self.feedback_logs = []
        except Exception:
            self.soul_map_state = {}
            self.feedback_logs = []

    def _save_to_disk(self):
        dir_name = os.path.dirname(self.persistence_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        key = _pending_key(self.persistence_path)
        flushed = {"through": 0}

        def _apply(blob: Dict[str, Any]) -> None:
            # This bridge's snapshot is stale. Keep the persisted ledger and trail rows that other
            # bridges wrote, and union this bridge's own ledger ids (replay guard).
            current = blob.get("soul_map_state")
            current_state = current if isinstance(current, dict) else {}
            current_ledger = current_state.get("resolved_prediction_ids")
            own_ledger = self.soul_map_state.get("resolved_prediction_ids")
            if isinstance(current_ledger, list) or isinstance(own_ledger, list):
                merged: list = list(current_ledger) if isinstance(current_ledger, list) else []
                for prediction_id in own_ledger if isinstance(own_ledger, list) else []:
                    if prediction_id not in merged:
                        merged.append(prediction_id)
                self.soul_map_state["resolved_prediction_ids"] = merged
            if "learning_trail" in current_state:
                self.soul_map_state["learning_trail"] = current_state["learning_trail"]
            else:
                self.soul_map_state.pop("learning_trail", None)
            # Rows whose earlier save failed never reached disk. Replay the buffered rows onto the
            # disk trail so this save keeps them.
            through, rows = _snapshot_pending(key)
            flushed["through"] = through
            _replay_trail_rows(self.soul_map_state, rows)
            blob["soul_map_state"] = self.soul_map_state
            blob["feedback_logs"] = self.feedback_logs

        try:
            committed, _ = write_soul_map_committed(_apply, self.persistence_path)
        except Exception:
            return
        if committed:
            _drop_pending_through(key, flushed["through"])

    def append_learning_trail(self, entry: Dict[str, Any], *, resolved_prediction_id: Any = None) -> None:
        """Append a mind-map learning trail row (pick/resolve/rotation events).

        A resolved prediction id is also recorded in ``resolved_prediction_ids`` in the same save.
        That ledger is never truncated, so a replay still matches after the trail window moves on.
        """
        key = _pending_key(self.persistence_path)
        _enqueue_pending(key, entry, resolved_prediction_id)
        flushed = {"through": 0}

        def _apply(blob: Dict[str, Any]) -> None:
            # Mutate the latest on-disk blob under the save lock, not this bridge's
            # snapshot, so another bridge's earlier append survives this save.
            state = blob.get("soul_map_state")
            if not isinstance(state, dict):
                state = {}
                blob["soul_map_state"] = state
            through, rows = _snapshot_pending(key)
            flushed["through"] = through
            _replay_trail_rows(state, rows)

        committed, result = write_soul_map_committed(_apply, self.persistence_path)
        if committed:
            # The disk write landed. Drop only the rows this commit carried, then sync the rows
            # and ledger to the merged on-disk state, so rows other bridges appended since this
            # bridge loaded are visible here too.
            _drop_pending_through(key, flushed["through"])
            committed_state = result.get("soul_map_state")
            committed_state = committed_state if isinstance(committed_state, dict) else {}
            for key in ("learning_trail", "resolved_prediction_ids"):
                if key in committed_state:
                    self.soul_map_state[key] = committed_state[key]
                else:
                    self.soul_map_state.pop(key, None)
        else:
            # The disk write failed. Keep this row in memory; the returned blob is the
            # pre-append snapshot and would drop it. Earlier failed rows are already in
            # memory from their own attempts, so only this row is added here.
            _replay_trail_rows(self.soul_map_state, [(entry, resolved_prediction_id)])

    def get_brain_recommendations(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retrieves the Brain's recommendations from the Mindmap.
        
        Args:
            context (dict, optional): Real context to enrich recommendations.
            
        Returns:
            dict: A dictionary of subnet IDs mapped to recommended actions/scores.
        """
        recommendations = {}
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r") as f:
                    registry = json.load(f)
                for sub_id, info in registry.items():
                    status = info.get("status", "active")
                    is_overvalued = info.get("is_overvalued", False)
                    emission = info.get("emission", 0.0)
                    social_mentions = info.get("social_mentions", 0)
                    
                    # If context has more up-to-date metrics, use them
                    if context:
                        # Try integer key first, then string key
                        sub_ctx = context.get(int(sub_id)) or context.get(str(sub_id))
                        if sub_ctx:
                            is_overvalued = sub_ctx.get("is_overvalued", is_overvalued)
                            emission = sub_ctx.get("emission", emission)
                            social_mentions = sub_ctx.get("social_mentions", social_mentions)
                    
                    if status == "deprecated" or is_overvalued:
                        action = "reduce"
                        target_weight = 0.1
                    elif emission > 1.5 and social_mentions > 1000:
                        action = "accumulate"
                        target_weight = 0.8
                    else:
                        action = "hold"
                        target_weight = 0.5
                        
                    recommendations[str(sub_id)] = {
                        "action": action,
                        "target_weight": target_weight,
                        "status": status,
                        "metrics": {
                            "emission": emission,
                            "social_mentions": social_mentions,
                            "is_overvalued": is_overvalued,
                            "emission_rank": info.get("emission_rank"),
                            "staking_data": info.get("staking_data")
                        }
                    }
            except Exception:
                pass
                
        # Fallback: honest-empty — never invent SN1/2/3 theater (LB-10)
        if not recommendations:
            return {
                "recommendations": {},
                "data_available": False,
                "source": "registry_heuristic",
                "reason": "no_registry_recommendations",
            }

        return {
            "recommendations": recommendations,
            "data_available": True,
            "source": "registry_heuristic",
        }

    def update_soul_map(self, selector_output: Dict[str, Any]) -> bool:
        """
        Updates the Soul-Map state with the Selector's daily output.
        
        Args:
            selector_output (dict): The daily output from the Selector.
            
        Returns:
            bool: True if the update was successful, False otherwise.
        """
        self.soul_map_state["last_selector_output"] = selector_output
        self.soul_map_state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._save_to_disk()
        return True

    def log_feedback(self, daily_output: Dict[str, Any], brain_recommendation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Logs feedback comparing daily output against brain recommendations.
        
        Args:
            daily_output (dict): The Selector's daily output.
            brain_recommendation (dict): The Brain's recommendations.
            
        Returns:
            dict: The feedback loop analysis.
        """
        scores = []
        recommendations = brain_recommendation.get("recommendations", {})
        for decision in daily_output.get("decisions", []):
            sub_id = str(decision.get("subnet_id"))
            sel_action = decision.get("recommended_action")
            brain_rec = recommendations.get(sub_id)
            if brain_rec:
                brain_action = brain_rec.get("action")
                if sel_action == brain_action:
                    score = 1.0
                elif (sel_action == "hold" and brain_action in ("accumulate", "reduce")) or \
                     (brain_action == "hold" and sel_action in ("accumulate", "reduce")):
                    score = 0.5
                else:
                    score = 0.0
                scores.append(score)
            else:
                scores.append(0.5)
                
        alignment_score = sum(scores) / len(scores) if scores else 1.0
        alignment_score = round(alignment_score, 4)
        
        if alignment_score >= 0.75:
            status = "aligned"
        elif alignment_score >= 0.4:
            status = "partially_aligned"
        else:
            status = "divergent"
            
        feedback = {
            "daily_output": daily_output,
            "brain_recommendation": brain_recommendation,
            "alignment_score": alignment_score,
            "status": status
        }
        self.feedback_logs.append(feedback)
        if len(self.feedback_logs) > FEEDBACK_LOGS_MAX:
            self.feedback_logs = self.feedback_logs[-FEEDBACK_LOGS_MAX:]
        self._save_to_disk()
        return feedback