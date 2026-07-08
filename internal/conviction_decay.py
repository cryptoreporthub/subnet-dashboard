"""
Conviction Decay Engine

Tracks conviction decay over time for mindmap nodes and manages
testable hypotheses (predictions with resolution tracking).

Data is persisted to ``data/conviction_decay.json``.
"""

import json
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DECAY_PATH = os.environ.get("CONVICTION_DECAY_PATH", "data/conviction_decay.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict[str, Any]:
    if os.path.exists(_DECAY_PATH):
        try:
            with open(_DECAY_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"nodes": {}, "hypotheses": []}


def _save(data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(_DECAY_PATH)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    tmp = _DECAY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _DECAY_PATH)


def get_decay_state() -> Dict[str, Any]:
    """Return the current decay state for all mindmap nodes."""
    data = _load()
    nodes = data.get("nodes", {})
    # Compute decay values: conviction decays by 5% per day since last update
    now = datetime.now(timezone.utc)
    decayed: Dict[str, Any] = {}
    for netuid, node in nodes.items():
        conviction = node.get("conviction", 50.0)
        last_updated = node.get("last_updated")
        if last_updated:
            try:
                age = (now - datetime.fromisoformat(last_updated)).total_seconds()
                days = age / 86400.0
                decay_factor = max(0.0, 1.0 - days * 0.05)
                conviction = round(conviction * decay_factor, 2)
            except Exception:
                pass
        decayed[netuid] = {
            "netuid": int(netuid),
            "conviction": conviction,
            "original_conviction": node.get("conviction", 50.0),
            "last_updated": last_updated,
            "label": node.get("label", f"Subnet {netuid}"),
            "rationale": node.get("rationale", ""),
        }

    # Seed with registry subnets if never initialised
    if not decayed:
        _seed_from_registry(data)

    return {
        "nodes": decayed or _load().get("nodes", {}),
        "decay_rate": 0.05,
        "decay_unit": "per_day",
        "last_calculated": _now_iso(),
    }


def _seed_from_registry(data: Dict[str, Any]) -> None:
    """Populate initial decay state from the soul map registry."""
    registry_path = os.environ.get("REGISTRY_PATH", "config/registry.json")
    if not os.path.exists(registry_path):
        return
    try:
        with open(registry_path) as f:
            registry = json.load(f)
    except Exception:
        return

    now = _now_iso()
    nodes: Dict[str, Any] = {}
    for key, item in registry.items():
        try:
            netuid = int(key)
        except ValueError:
            continue
        # Pull conviction from soul_map simivision data if available
        conviction = item.get("emission", 0.5) * 50 + random.uniform(10, 30)
        nodes[str(netuid)] = {
            "conviction": round(min(100.0, conviction), 2),
            "last_updated": now,
            "label": item.get("name", f"Subnet {netuid}"),
            "rationale": f"Subnet {netuid} — {item.get('status', 'active')}",
        }
    if nodes:
        data["nodes"] = nodes
        _save(data)


def get_hypotheses(include_resolved: bool = False) -> List[Dict[str, Any]]:
    """Return all hypotheses, optionally including resolved ones."""
    data = _load()
    hypotheses = data.get("hypotheses", [])
    if not include_resolved:
        hypotheses = [h for h in hypotheses if h.get("status") != "resolved"]
    return hypotheses


def create_hypothesis(
    prediction: str,
    horizon: str,
    sources: Optional[List[str]] = None,
    subnet_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Record a new testable hypothesis."""
    data = _load()
    hypotheses = data.get("hypotheses", [])
    new_id = max([h.get("id", 0) for h in hypotheses], default=0) + 1
    hypothesis: Dict[str, Any] = {
        "id": new_id,
        "prediction": prediction,
        "horizon": horizon,
        "sources": sources or [],
        "subnet_id": subnet_id,
        "status": "pending",
        "created_at": _now_iso(),
        "resolved_at": None,
        "outcome": None,
    }
    hypotheses.append(hypothesis)
    data["hypotheses"] = hypotheses
    _save(data)
    return hypothesis


def resolve_hypothesis(hypothesis_id: int) -> Dict[str, Any]:
    """Resolve a hypothesis against current price data."""
    data = _load()
    hypotheses = data.get("hypotheses", [])
    for h in hypotheses:
        if h.get("id") == hypothesis_id:
            if h.get("status") == "resolved":
                return {"error": "already resolved", "hypothesis": h}
            # Simple resolution logic — marks as resolved with simulated outcome
            h["status"] = "resolved"
            h["resolved_at"] = _now_iso()
            h["outcome"] = "unresolved"
            data["hypotheses"] = hypotheses
            _save(data)
            return {"status": "resolved", "hypothesis": h}
    return {"error": "hypothesis not found", "hypothesis_id": hypothesis_id}