"""Pump desk intelligence snapshot — read-only ops probe (no pick scoring).

Fetches pump desk + daily pick status + learning health via internal calls
(not HTTP self-wedge). Writes ``data/pump_desk/snapshots/`` for Ditto/GHA alerts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PUMP_DESK_DIR = os.environ.get("PUMP_DESK_SNAPSHOT_DIR", os.path.join("data", "pump_desk"))
ALERT_BADGES = frozenset({"BUILDING", "JUST STARTED"})
SNAPSHOT_STAGE_TIMEOUT_SECONDS = max(
    1.0, float(os.environ.get("PUMP_DESK_SNAPSHOT_STAGE_TIMEOUT_SECONDS", "30"))
)


def _desk_dir() -> str:
    return os.environ.get("PUMP_DESK_SNAPSHOT_DIR", PUMP_DESK_DIR)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stage_with_timeout(
    label: str,
    fn,
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep one slow collector from preventing the snapshot artifact."""
    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            value = fn()
            if isinstance(value, dict):
                result["value"] = value
            else:
                error["value"] = TypeError(f"{label} returned a non-object")
        except BaseException as exc:
            error["value"] = exc
        finally:
            done.set()

    threading.Thread(target=_run, daemon=True, name=f"pump-snapshot-{label}").start()
    if not done.wait(timeout=SNAPSHOT_STAGE_TIMEOUT_SECONDS):
        logger.warning(
            "pump desk snapshot stage timed out: %s after %.1fs",
            label,
            SNAPSHOT_STAGE_TIMEOUT_SECONDS,
        )
        return dict(fallback)
    if "value" in error:
        raise error["value"]
    return result.get("value") or dict(fallback)


def _snapshot_path(ts: Optional[str] = None) -> str:
    name = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    return os.path.join(_desk_dir(), "snapshots", f"{name}.json")


def _latest_path() -> str:
    return os.path.join(_desk_dir(), "latest.json")


def _collect_pump_desk() -> Dict[str, Any]:
    try:
        from internal.pump.desk_payload import load_pump_alerts_desk_payload

        return _run_stage_with_timeout(
            "pump-desk",
            load_pump_alerts_desk_payload,
            {
                "status": "timeout",
                "count": 0,
                "alerts": [],
                "error": "pump desk collector timed out",
            },
        )
    except Exception as exc:
        logger.warning("pump desk snapshot: pump_alerts failed: %s", exc)
        return {
            "status": "error",
            "count": 0,
            "alerts": [],
            "error": str(exc),
        }


def _collect_learning_health() -> Dict[str, Any]:
    try:
        from internal.learning.loop_health import build_learning_loop_health

        return _run_stage_with_timeout(
            "learning-health",
            build_learning_loop_health,
            {
                "status": "degraded",
                "error": "learning health collector timed out",
            },
        )
    except Exception as exc:
        logger.warning("pump desk snapshot: learning health failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _badge_rows(pump: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for alt in pump.get("alerts") or []:
        if not isinstance(alt, dict):
            continue
        badge = str(alt.get("badge") or "").upper()
        if badge in ALERT_BADGES:
            rows.append(
                {
                    "netuid": alt.get("netuid"),
                    "name": alt.get("name"),
                    "badge": badge,
                    "move": alt.get("move"),
                }
            )
    return rows


def _evaluate_alerts(
    pump: Dict[str, Any],
    health: Dict[str, Any],
) -> Tuple[str, List[str]]:
    """Return (level, reasons). level: ok | warn | alert."""
    reasons: List[str] = []
    pump_status = str(pump.get("status") or "").lower()
    if pump_status in ("unavailable", "timeout", "error"):
        reasons.append(f"pump-alerts status={pump_status}")
    health_status = str(health.get("status") or "").lower()
    if health_status in ("stalled", "error"):
        reasons.append(f"learning_loop status={health_status}")
    if health_status == "ok" and not (health.get("worker_peer") or {}).get("alive"):
        reasons.append("worker_peer not alive")

    building = _badge_rows(pump)
    if building:
        names = ", ".join(f"SN{r.get('netuid')} {r.get('badge')}" for r in building[:5])
        reasons.append(f"actionable badges: {names}")

    if any(r.startswith("pump-alerts") or r.startswith("learning_loop") or "worker_peer" in r for r in reasons):
        return "alert", reasons
    if building:
        return "warn", reasons
    if health_status == "degraded":
        return "warn", reasons + ["learning_loop degraded"]
    return "ok", reasons


def build_pump_desk_snapshot() -> Dict[str, Any]:
    pump = _collect_pump_desk()
    health = _collect_learning_health()
    level, reasons = _evaluate_alerts(pump, health)
    daily = (health.get("daily_pick") or {}) if isinstance(health.get("daily_pick"), dict) else {}

    return {
        "status": "ok",
        "captured_at": _utcnow_iso(),
        "alert_level": level,
        "alert_reasons": reasons,
        "pump_desk": {
            "status": pump.get("status"),
            "count": pump.get("count"),
            "early_count": pump.get("early_count"),
            "confirmed_count": pump.get("confirmed_count"),
            "error": pump.get("error"),
        },
        "daily_pick": daily,
        "learning_loop": {
            "status": health.get("status"),
            "pending": health.get("pending"),
            "worker_peer_alive": (health.get("worker_peer") or {}).get("alive"),
        },
        "actionable_badges": _badge_rows(pump),
    }


def save_snapshot(payload: Dict[str, Any]) -> str:
    desk = _desk_dir()
    os.makedirs(os.path.join(desk, "snapshots"), exist_ok=True)
    path = _snapshot_path()
    latest = _latest_path()
    for target in (path, latest):
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, target)
    return path


def run_snapshot(*, save: bool = True) -> Dict[str, Any]:
    payload = build_pump_desk_snapshot()
    if save:
        payload["path"] = save_snapshot(payload)
    return payload


def exit_code_for_level(level: str) -> int:
    """0 ok/warn informational; 2 alert (ops pager)."""
    if level == "alert":
        return 2
    return 0


def load_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Read the most recent persisted desk snapshot, if any."""
    try:
        with open(_latest_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def summarize_pump_desk_snapshot() -> Dict[str, Any]:
    """Plain-language summary from data/pump_desk/latest.json (Phase C display)."""
    snap = load_latest_snapshot()
    parts: List[str] = []
    if not snap:
        parts.append(
            "No pump desk snapshots on disk yet — the inline scheduler writes "
            "data/pump_desk/snapshots/ every 15 minutes when PUMP_DESK_SNAPSHOT_ENABLED is on."
        )
        return {"text": " ".join(parts), "sentences": parts}

    level = str(snap.get("alert_level") or "ok")
    captured = snap.get("captured_at") or "unknown time"
    pump = snap.get("pump_desk") or {}
    badges = snap.get("actionable_badges") or []
    parts.append(
        f"Latest pump desk snapshot ({captured}) is alert_level={level} "
        f"with {pump.get('count', 0)} ladder rows on the desk."
    )
    if badges:
        names = ", ".join(
            f"SN{b.get('netuid')} {b.get('badge')}" for b in badges[:3] if isinstance(b, dict)
        )
        parts.append(f"Actionable badges in that snapshot: {names}.")
    else:
        parts.append("No BUILDING or JUST STARTED badges were flagged in the latest snapshot.")
    loop = snap.get("learning_loop") or {}
    parts.append(
        f"Learning loop was {loop.get('status', 'unknown')} with {loop.get('pending', 0)} pending "
        "predictions when the snapshot was taken."
    )
    text = " ".join(p for p in parts if p)
    return {"text": text, "sentences": parts[:4]}
