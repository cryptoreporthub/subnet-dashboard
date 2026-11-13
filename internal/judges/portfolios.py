"""
Paper portfolio persistence for the Oracle / Echo / Pulse judges.

Each judge keeps a ledger of open and closed paper positions. Positions are
sized by the judge's confidence at entry time and closed when the underlying
prediction resolves. Performance is tracked overall and split by hourly vs
daily horizon.

Each judge has a different risk profile:
  - Oracle: standard risk (truth-focused, 1.0x)
  - Echo: conservative risk (consensus-focused, 0.7x)
  - Pulse: aggressive risk (momentum-focused, 1.3x)
"""

from __future__ import annotations

import json
import fcntl
import os
import threading
import time
import contextvars
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, Iterator, List, Optional, Tuple

PORTFOLIOS_PATH = os.path.join("data", "judge_portfolios.json")
_PORTFOLIOS_MUTEX = threading.RLock()
PORTFOLIOS_LOCK_TIMEOUT_SECONDS = 5.0
_operation_deadline: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "portfolios_operation_deadline", default=None
)


class PortfolioLockTimeout(TimeoutError):
    """Raised when the portfolios mutex or flock is not acquired before the deadline."""


class PortfolioUnreadable(Exception):
    """Raised when the portfolios book exists but cannot be read."""


@contextmanager
def portfolios_operation_deadline(seconds: Optional[float] = None) -> Iterator[None]:
    """Set a shared absolute deadline for nested portfolio lock acquisitions.

    If a parent deadline is already set, inherit it (do not reset).
    ContextVar does not propagate into new threads; share a deadline only
    in the same thread (the 3-judge close loop is sequential in-thread).
    """
    if _operation_deadline.get() is not None:
        yield
        return
    timeout = PORTFOLIOS_LOCK_TIMEOUT_SECONDS if seconds is None else seconds
    token = _operation_deadline.set(time.monotonic() + float(timeout))
    try:
        yield
    finally:
        _operation_deadline.reset(token)

# Per-judge risk multipliers — each judge trades with different conviction sizing
_JUDGE_RISK_MULTIPLIER = {
    "oracle": 1.0,   # Standard risk — truth-focused, balanced sizing
    "echo": 0.7,     # Conservative — consensus-focused, smaller positions
    "pulse": 1.3,    # Aggressive — momentum-focused, larger positions
}

_DEFAULT_JUDGE = {
    "open_positions": [],
    "closed_positions": [],
    "summary": {
        "open_positions": 0,
        "total_closed": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_pct": 0.0,
        "total_pnl_pct": 0.0,
        "hourly": {"total": 0, "wins": 0, "win_pct": 0.0, "pnl_pct": 0.0},
        "daily": {"total": 0, "wins": 0, "win_pct": 0.0, "pnl_pct": 0.0},
    },
}

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _load() -> Dict[str, Any]:
    try:
        with open(PORTFOLIOS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _load_checked() -> Dict[str, Any]:
    obs = observe_portfolios()
    if obs["kind"] == "missing":
        return {}
    if obs["kind"] != "readable":
        raise ValueError(obs.get("error") or "unreadable portfolios")
    return obs["data"]


def _shape_error(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return "portfolios root must be an object"
    for judge in data.values():
        if not isinstance(judge, dict) or any(
            not isinstance(judge.get(key, []), list) for key in ("open_positions", "closed_positions")
        ) or not isinstance(judge.get("closed_prediction_ids", {}), dict):
            return "invalid judge portfolio"
    return None


def observe_portfolios() -> Dict[str, Any]:
    """Fail-closed portfolio readability: never use get_portfolio / _load()."""
    try:
        with open(PORTFOLIOS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"kind": "missing", "data": {}, "error": "missing"}
    except Exception as exc:
        return {"kind": "unreadable", "data": {}, "error": f"{type(exc).__name__}: {exc}"}
    error = _shape_error(data)
    if error:
        return {"kind": "unreadable", "data": {}, "error": error}
    return {"kind": "readable", "data": data, "error": None}


def _prediction_is_terminal(pred_id: Any) -> bool:
    if pred_id is None:
        return False
    try:
        from internal.learning.predictions_store import prediction_is_terminal

        return bool(prediction_is_terminal(pred_id))
    except Exception:
        return False


def _position_identity(source: Optional[Dict[str, Any]]) -> Tuple[Any, Any]:
    if not source:
        return (None, None)
    created = source.get("prediction_created_at")
    if created is None:
        created = source.get("created_at")
    return (created, source.get("horizon_type"))


def _idless_identity_complete(created: Any, horizon: Any) -> bool:
    return created is not None and horizon is not None


def _position_matches(
    pos: Dict[str, Any],
    pred_id: Any,
    netuid: Any = None,
    row: Optional[Dict[str, Any]] = None,
) -> bool:
    if pred_id is not None:
        return pos.get("id") == pred_id
    if pos.get("id") is not None:
        return False
    if netuid is None or pos.get("netuid") != netuid:
        return False
    row_created, row_horizon = _position_identity(row)
    pos_created, pos_horizon = _position_identity(pos)
    if not _idless_identity_complete(row_created, row_horizon) or not _idless_identity_complete(pos_created, pos_horizon):
        return False
    return row_created == pos_created and row_horizon == pos_horizon


def _idless_ambiguous(
    pos: Dict[str, Any],
    pred_id: Any,
    netuid: Any = None,
    row: Optional[Dict[str, Any]] = None,
) -> bool:
    if pred_id is not None or pos.get("id") is not None:
        return False
    if netuid is None or pos.get("netuid") != netuid:
        return False
    row_created, row_horizon = _position_identity(row)
    pos_created, pos_horizon = _position_identity(pos)
    return not (
        _idless_identity_complete(row_created, row_horizon)
        and _idless_identity_complete(pos_created, pos_horizon)
    )


def holds_open(
    judge_name: str,
    pred_id: Any,
    *,
    data: Optional[Dict[str, Any]] = None,
    netuid: Any = None,
    row: Optional[Dict[str, Any]] = None,
) -> bool:
    if data is None:
        obs = observe_portfolios()
        if obs["kind"] == "missing":
            return False
        if obs["kind"] != "readable":
            raise PortfolioUnreadable(obs.get("error") or "unreadable portfolios")
        data = obs["data"]
    if pred_id is None and netuid is None:
        return False
    judge = data.get(str(judge_name).lower()) or {}
    return any(
        _position_matches(pos, pred_id, netuid, row=row) or _idless_ambiguous(pos, pred_id, netuid, row=row)
        for pos in judge.get("open_positions") or []
    )


def holds_closed(judge_name: str, pred_id: Any, *, data: Optional[Dict[str, Any]] = None, netuid: Any = None, row: Optional[Dict[str, Any]] = None) -> bool:
    if data is None:
        obs = observe_portfolios()
        if obs["kind"] == "missing":
            return False
        if obs["kind"] != "readable":
            raise PortfolioUnreadable(obs.get("error") or "unreadable portfolios")
        data = obs["data"]
    if pred_id is None and netuid is None:
        return False
    judge = data.get(str(judge_name).lower()) or {}
    return any(_position_matches(pos, pred_id, netuid, row=row) for pos in judge.get("closed_positions") or [])


def _closed_row_from_prediction(
    judge_name: str,
    prediction: Dict[str, Any],
    *,
    position: Optional[Dict[str, Any]] = None,
    actual_pct: Optional[float] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    direction = (position or {}).get("direction") or prediction.get("direction", "up")
    predicted_pct = float((position or {}).get("predicted_pct", prediction.get("predicted_pct", 0)) or 0)
    if actual_pct is None:
        ref = float(prediction.get("reference_price", 0) or 0)
        resolved_price = float(prediction.get("resolved_price", 0) or 0)
        if ref > 0 and resolved_price > 0:
            actual_pct = (resolved_price - ref) / ref * 100
        else:
            actual_pct = 0.0
    actual_pct = float(actual_pct or 0)
    if position is None:
        position = {
            "id": prediction.get("id"),
            "netuid": prediction.get("netuid"),
            "name": prediction.get("name"),
            "direction": direction,
            "predicted_pct": predicted_pct,
            "reference_price": float(prediction.get("reference_price", 0) or 0),
            "size": 1.0,
            "bucket": _bucket(prediction.get("horizon_hours")),
            "horizon_hours": prediction.get("horizon_hours"),
            "entered_at": prediction.get("created_at"),
        }
    pnl = _compute_pnl(direction, predicted_pct, actual_pct, judge_name)
    return {
        **position,
        "actual_pct": round(actual_pct, 4),
        "pnl_pct": round(pnl * position.get("size", 1.0), 4),
        "outcome": outcome or prediction.get("outcome", "unknown"),
        "closed_at": _utcnow(),
    }

@contextmanager
def _portfolios_lock(*, deadline: Optional[float] = None) -> Iterator[None]:
    """Acquire the in-process mutex and the on-disk flock, or time out.

    Mutex serializes threads, flock serializes processes; nesting is unsupported.
    The timeout constant is read inside this function so tests can patch it.
    """
    if deadline is None:
        deadline = _operation_deadline.get()
        if deadline is None:
            deadline = time.monotonic() + PORTFOLIOS_LOCK_TIMEOUT_SECONDS

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PortfolioLockTimeout("portfolios lock deadline already passed")

    acquired = _PORTFOLIOS_MUTEX.acquire(timeout=max(0.0, remaining))
    try:
        if not acquired:
            raise PortfolioLockTimeout("timed out waiting for portfolios mutex")
        os.makedirs(os.path.dirname(PORTFOLIOS_PATH) or ".", exist_ok=True)
        with open(PORTFOLIOS_PATH + ".lock", "a+", encoding="utf-8") as lock:
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                raise PortfolioLockTimeout("timed out waiting for portfolios flock")
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        if acquired:
            _PORTFOLIOS_MUTEX.release()

def _portfolio_transaction(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with _portfolios_lock():
            return fn(*args, **kwargs)
    return run

def _prune_tombstones(judge: Dict[str, Any]) -> None:
    from internal.learning.pick_horizon import day_horizon_hours

    cutoff = datetime.now(timezone.utc) - timedelta(hours=day_horizon_hours() + 49)
    tombstones = judge.setdefault("closed_prediction_ids", {})
    for key, value in list(tombstones.items()):
        try:
            if datetime.fromisoformat(value.replace("Z", "+00:00")) < cutoff:
                del tombstones[key]
        except (ValueError, AttributeError, TypeError):
            continue

def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(PORTFOLIOS_PATH) or ".", exist_ok=True)
    tmp = PORTFOLIOS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PORTFOLIOS_PATH)

def _get_judge(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    name = name.lower()
    if name not in data:
        data[name] = json.loads(json.dumps(_DEFAULT_JUDGE))
    return data[name]

def _compute_pnl(direction: str, predicted_pct: float, actual_pct: float, judge_name: str = "oracle") -> float:
    """P&L for a paper position: aligned move positive, opposite move negative.
    
    Scaled by the judge's risk multiplier so each judge has differentiated returns.
    """
    if direction == "down":
        base_pnl = -actual_pct
    else:
        base_pnl = actual_pct
    multiplier = _JUDGE_RISK_MULTIPLIER.get(judge_name.lower(), 1.0)
    return round(base_pnl * multiplier, 4)

def _bucket(horizon_hours: Optional[int]) -> str:
    if horizon_hours is None:
        return "daily"
    return "hourly" if horizon_hours < 24 else "daily"

def _recompute_summary(judge_data: Dict[str, Any]) -> None:
    closed = judge_data.get("closed_positions", [])
    wins = [p for p in closed if p.get("pnl_pct", 0) > 0]
    losses = [p for p in closed if p.get("pnl_pct", 0) <= 0]

    hourly_closed = [p for p in closed if p.get("bucket") == "hourly"]
    hourly_wins = [p for p in hourly_closed if p.get("pnl_pct", 0) > 0]
    daily_closed = [p for p in closed if p.get("bucket") == "daily"]
    daily_wins = [p for p in daily_closed if p.get("pnl_pct", 0) > 0]

    def _bucket_stats(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(positions)
        wins_count = len([p for p in positions if p.get("pnl_pct", 0) > 0])
        return {
            "total": total,
            "wins": wins_count,
            "win_pct": round(wins_count / total, 4) if total else 0.0,
            "pnl_pct": round(sum(p.get("pnl_pct", 0) for p in positions), 4),
        }

    total_closed = len(closed)
    judge_data["summary"] = {
        "open_positions": len(judge_data.get("open_positions", [])),
        "total_closed": total_closed,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_pct": round(len(wins) / total_closed, 4) if total_closed else 0.0,
        "total_pnl_pct": round(sum(p.get("pnl_pct", 0) for p in closed), 4),
        "hourly": _bucket_stats(hourly_closed),
        "daily": _bucket_stats(daily_closed),
    }

def _open_position(data, judge_name, prediction, size):
    judge = _get_judge(data, judge_name)
    _prune_tombstones(judge)
    pred_id = prediction.get("id")
    if pred_id is not None and (
        str(pred_id) in judge.get("closed_prediction_ids", {})
        or any(pos.get("id") == pred_id for pos in judge.get("open_positions", []))
        or any(pos.get("id") == pred_id for pos in judge.get("closed_positions", []))
    ):
        return None
    name_lower = judge_name.lower()
    risk_mult = _JUDGE_RISK_MULTIPLIER.get(name_lower, 1.0)
    horizon = prediction.get("horizon_hours")
    position = {
        "id": pred_id, "netuid": prediction.get("netuid"), "name": prediction.get("name"),
        "direction": prediction.get("direction", "up"),
        "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
        "reference_price": float(prediction.get("reference_price", 0) or 0),
        "size": round(float(size) * risk_mult, 4), "risk_multiplier": risk_mult,
        "bucket": _bucket(horizon), "horizon_hours": horizon, "entered_at": _utcnow(),
        "prediction_created_at": prediction.get("created_at"),
        "horizon_type": prediction.get("horizon_type"),
    }
    judge.setdefault("open_positions", []).append(position)
    _recompute_summary(judge)
    return position


def open_positions_for_prediction(prediction: Dict[str, Any], scores: Dict[str, Any]) -> None:
    # Unlocked early exit; the in-lock recheck immediately before _save is the real gate.
    if _prediction_is_terminal(prediction.get("id")):
        return
    _open_positions_for_prediction_locked(prediction, scores)


@_portfolio_transaction
def _open_positions_for_prediction_locked(prediction: Dict[str, Any], scores: Dict[str, Any]) -> None:
    data = _load_checked()
    changed = False
    for name in ("oracle", "echo", "pulse"):
        confidence = float((scores.get(name) or {}).get("confidence", 0.5) or 0.5)
        changed |= _open_position(data, name, prediction, 0.5 + 0.5 * confidence) is not None
    if changed:
        if _prediction_is_terminal(prediction.get("id")):
            return
        _save(data)


def open_position(
    judge_name: str,
    prediction: Dict[str, Any],
    size: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Open a paper position for a judge when a prediction is created."""
    if _prediction_is_terminal(prediction.get("id")):
        return None
    return _open_position_locked(judge_name, prediction, size)


@_portfolio_transaction
def _open_position_locked(
    judge_name: str,
    prediction: Dict[str, Any],
    size: float = 1.0,
) -> Optional[Dict[str, Any]]:
    data = _load_checked()
    position = _open_position(data, judge_name, prediction, size)
    if position is not None:
        if _prediction_is_terminal(prediction.get("id")):
            return None
        _save(data)
    return position

@_portfolio_transaction
def discard_open_position(judge_name: str, prediction_id: Any) -> bool:
    """Remove an open paper position without closing it to the ledger."""
    if prediction_id is None:
        return False
    data = _load_checked()
    judge = _get_judge(data, judge_name)
    open_positions = judge.get("open_positions", [])
    remaining = [pos for pos in open_positions if pos.get("id") != prediction_id]
    if len(remaining) == len(open_positions):
        return False
    judge["open_positions"] = remaining
    _recompute_summary(judge)
    _save(data)
    return True


@_portfolio_transaction
def close_position(
    judge_name: str,
    prediction: Dict[str, Any],
    actual_pct: Optional[float] = None,
    outcome: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Close an open paper position and move it to the closed ledger.

    Close-without-open is a no-op: no fabricated row, no tombstone, no new
    judge key, and no file create.
    """
    obs = observe_portfolios()
    if obs["kind"] == "unreadable":
        raise PortfolioUnreadable(obs.get("error") or "unreadable portfolios")
    if obs["kind"] != "readable":
        return None
    data = obs["data"]
    name = judge_name.lower()
    judge = data.get(name)
    if not isinstance(judge, dict):
        return None
    open_positions = judge.get("open_positions", [])
    pred_id = prediction.get("id")
    netuid = prediction.get("netuid")
    _prune_tombstones(judge)

    if pred_id is not None and any(
        c.get("id") == pred_id for c in judge.get("closed_positions", [])
    ):
        remaining = [pos for pos in open_positions if pos.get("id") != pred_id]
        if len(remaining) != len(open_positions):
            judge["open_positions"] = remaining
            _recompute_summary(judge)
            _save(data)
        return None

    idx = next(
        (
            i
            for i, pos in enumerate(open_positions)
            if _position_matches(pos, pred_id, netuid, row=prediction)
        ),
        None,
    )
    if idx is None:
        return None

    position = open_positions.pop(idx)
    closed = _closed_row_from_prediction(
        name, prediction, position=position, actual_pct=actual_pct, outcome=outcome
    )
    if pred_id is not None:
        judge.setdefault("closed_prediction_ids", {})[str(pred_id)] = _utcnow()
    judge.setdefault("closed_positions", []).append(closed)
    _recompute_summary(judge)
    _save(data)
    return closed


@_portfolio_transaction
def backfill_closed_position(
    judge_name: str,
    prediction: Dict[str, Any],
    actual_pct: Optional[float] = None,
    outcome: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Rebuild-only: record a closed position without going through live open."""
    obs = observe_portfolios()
    if obs["kind"] == "unreadable":
        raise ValueError(obs.get("error") or "unreadable portfolios")
    data = obs["data"] if obs["kind"] == "readable" else {}
    name = judge_name.lower()
    judge = _get_judge(data, name)
    pred_id = prediction.get("id")
    if pred_id is not None and any(
        c.get("id") == pred_id for c in judge.get("closed_positions", [])
    ):
        remaining = [pos for pos in judge.get("open_positions", []) if pos.get("id") != pred_id]
        if len(remaining) != len(judge.get("open_positions", [])):
            judge["open_positions"] = remaining
            _recompute_summary(judge)
            _save(data)
        return None
    remaining = [pos for pos in judge.get("open_positions", []) if pos.get("id") != pred_id]
    position = None
    if len(remaining) != len(judge.get("open_positions", [])):
        position = next(
            (pos for pos in judge.get("open_positions", []) if pos.get("id") == pred_id),
            None,
        )
        judge["open_positions"] = remaining
    closed = _closed_row_from_prediction(
        name, prediction, position=position, actual_pct=actual_pct, outcome=outcome
    )
    if pred_id is not None:
        judge.setdefault("closed_prediction_ids", {})[str(pred_id)] = _utcnow()
    judge.setdefault("closed_positions", []).append(closed)
    _recompute_summary(judge)
    _save(data)
    return closed


def get_portfolio(judge_name: str) -> Dict[str, Any]:
    """Return the full portfolio state for a judge."""
    data = _load()
    judge = _get_judge(data, judge_name)
    _recompute_summary(judge)
    return judge

def all_portfolios() -> Dict[str, Any]:
    """Return every judge portfolio keyed by judge name (read-only)."""
    data = _load()
    for name in ("oracle", "echo", "pulse"):
        _recompute_summary(_get_judge(data, name))
    return data
