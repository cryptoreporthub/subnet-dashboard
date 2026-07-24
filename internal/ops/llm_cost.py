"""Rolling SimiVision chat LLM token usage for cost debugging."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_MAX_RECENT = 100
_LOCK = threading.Lock()


def _state_path() -> str:
    return os.environ.get("LLM_COST_PATH", "data/llm_cost.json")


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rates() -> tuple[float, float]:
    """USD per 1M tokens (input, output). Chutes DeepSeek TEE ≈ $1/M each."""
    inp = float(os.environ.get("LLM_COST_PER_M_INPUT", "1.0"))
    out = float(os.environ.get("LLM_COST_PER_M_OUTPUT", "1.0"))
    return inp, out


def _estimate_usd(prompt_tokens: int, completion_tokens: int) -> float:
    inp_rate, out_rate = _rates()
    return (prompt_tokens * inp_rate + completion_tokens * out_rate) / 1_000_000.0


def _empty_state() -> Dict[str, Any]:
    return {
        "updated_at": _utcnow_z(),
        "totals": {
            "calls": 0,
            "llm_calls": 0,
            "fallback_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_usd": 0.0,
        },
        "recent": [],
    }


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "totals" in data and "recent" in data:
            return data
    except Exception:
        pass
    return _empty_state()


def _save_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def record_chat_usage(
    *,
    llm_used: bool,
    model: str,
    provider: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    status: str = "ok",
) -> None:
    """Append one chat call to rolling stats (in-memory + JSON)."""
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    tt = max(0, int(total_tokens or 0)) or (pt + ct)
    usd = _estimate_usd(pt, ct) if llm_used else 0.0

    entry = {
        "at": _utcnow_z(),
        "llm_used": bool(llm_used),
        "model": model,
        "provider": provider,
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": tt,
        "estimated_usd": round(usd, 6),
        "status": status,
    }

    with _LOCK:
        state = _load_state()
        totals = state["totals"]
        totals["calls"] = int(totals.get("calls", 0)) + 1
        if llm_used:
            totals["llm_calls"] = int(totals.get("llm_calls", 0)) + 1
            totals["prompt_tokens"] = int(totals.get("prompt_tokens", 0)) + pt
            totals["completion_tokens"] = int(totals.get("completion_tokens", 0)) + ct
            totals["total_tokens"] = int(totals.get("total_tokens", 0)) + tt
            totals["estimated_usd"] = round(
                float(totals.get("estimated_usd", 0.0)) + usd, 6
            )
        else:
            totals["fallback_calls"] = int(totals.get("fallback_calls", 0)) + 1

        recent: List[Dict[str, Any]] = list(state.get("recent") or [])
        recent.append(entry)
        state["recent"] = recent[-_MAX_RECENT:]
        state["updated_at"] = _utcnow_z()
        _save_state(state)


def build_llm_cost_report() -> Dict[str, Any]:
    """Expose rolling token/cost stats for /api/ops/llm-cost."""
    inp_rate, out_rate = _rates()
    with _LOCK:
        state = _load_state()
    totals = dict(state.get("totals") or {})
    llm_calls = int(totals.get("llm_calls", 0))
    avg: Dict[str, Optional[float]] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "estimated_usd": None,
    }
    if llm_calls:
        avg["prompt_tokens"] = round(
            float(totals.get("prompt_tokens", 0)) / llm_calls, 2
        )
        avg["completion_tokens"] = round(
            float(totals.get("completion_tokens", 0)) / llm_calls, 2
        )
        avg["estimated_usd"] = round(
            float(totals.get("estimated_usd", 0.0)) / llm_calls, 6
        )

    return {
        "updated_at": state.get("updated_at"),
        "rates_per_million": {"input_usd": inp_rate, "output_usd": out_rate},
        "totals": totals,
        "averages_per_llm_call": avg,
        "recent": list(state.get("recent") or [])[-20:],
        "note": (
            "Estimated USD uses LLM_COST_PER_M_INPUT/OUTPUT (default $1/M each, "
            "Chutes DeepSeek TEE). Local fallback calls record zero tokens."
        ),
    }
