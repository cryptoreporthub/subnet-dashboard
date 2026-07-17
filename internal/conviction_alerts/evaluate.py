"""Conviction threshold evaluation for O1."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from internal.signals.alerts import AlertEngine

_ENABLED = frozenset({"1", "true", "on", "yes"})
# Match static/js/conviction_tiers.js (75/55/35)
_DEFAULT_THRESHOLDS = {"cyan": 75, "lime": 55, "gold": 35}
_last_run: Dict[str, Any] = {"last_run_at": None, "created": 0, "reason": "never_run"}


def conviction_alerts_enabled() -> bool:
    return os.environ.get("CONVICTION_ALERTS_ENABLED", "").lower() in _ENABLED


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_confidence(value: Any) -> float:
    try:
        conf = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if 0 < conf <= 1:
        conf *= 100
    return round(conf, 2)


def _tier_for(conf: float) -> str:
    if conf > _DEFAULT_THRESHOLDS["cyan"]:
        return "cyan"
    if conf > _DEFAULT_THRESHOLDS["lime"]:
        return "lime"
    if conf > _DEFAULT_THRESHOLDS["gold"]:
        return "gold"
    return "red"


def _load_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _collect_candidates() -> List[Dict[str, Any]]:
    """Honest-empty scan of persisted council conviction sources."""
    out: List[Dict[str, Any]] = []

    picks_path = os.environ.get("DAILY_PICKS_PATH", "data/daily_picks.json")
    picks = _load_json(picks_path)
    if isinstance(picks, list):
        for rec in reversed(picks):
            if rec.get("date") != _today_str():
                continue
            pick = rec.get("pick") or rec.get("candidate") or {}
            if not isinstance(pick, dict):
                break
            conf = _normalize_confidence(
                pick.get("final_confidence") or pick.get("confidence")
            )
            subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else pick
            netuid = subnet.get("netuid") if isinstance(subnet, dict) else pick.get("netuid")
            out.append(
                {
                    "source": "daily_pick",
                    "netuid": netuid,
                    "name": (subnet or {}).get("name") if isinstance(subnet, dict) else None,
                    "confidence": conf,
                    "tier": _tier_for(conf),
                    "action": pick.get("action"),
                }
            )
            break

    soul_path = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
    soul = _load_json(soul_path)
    if isinstance(soul, dict):
        decisions = (
            soul.get("soul_map_state", {})
            .get("last_selector_output", {})
            .get("decisions", [])
        )
        for d in decisions or []:
            if not isinstance(d, dict):
                continue
            conf = _normalize_confidence(
                d.get("final_confidence")
                or d.get("confidence")
                or d.get("score")
            )
            if conf <= 0:
                continue
            out.append(
                {
                    "source": "selector",
                    "netuid": d.get("subnet_id") or d.get("netuid"),
                    "name": d.get("name"),
                    "confidence": conf,
                    "tier": _tier_for(conf),
                    "action": d.get("action") or d.get("decision"),
                }
            )

    return out


def get_conviction_config() -> Dict[str, Any]:
    min_conf = float(os.environ.get("CONVICTION_ALERT_MIN", str(_DEFAULT_THRESHOLDS["cyan"])))
    from internal.conviction_alerts.delivery import delivery_mode

    return {
        "enabled": conviction_alerts_enabled(),
        "min_confidence": min_conf,
        "tiers": dict(_DEFAULT_THRESHOLDS),
        "delivery_mode": delivery_mode(),
        "env": {
            "CONVICTION_ALERTS_ENABLED": "off",
            "CONVICTION_ALERT_MIN": "75",
            "CONVICTION_ALERT_DELIVERY": "off|dry_run|webhook|telegram",
        },
    }


def _pending_by_netuid() -> Dict[int, List[Dict[str, Any]]]:
    data = _load_json(os.environ.get("PREDICTIONS_PATH", "data/predictions.json"))
    if not isinstance(data, dict):
        return {}
    out: Dict[int, List[Dict[str, Any]]] = {}
    for pred in data.get("predictions") or []:
        if not isinstance(pred, dict):
            continue
        if pred.get("status") not in (None, "pending"):
            continue
        n = pred.get("netuid")
        if n is None:
            continue
        out.setdefault(int(n), []).append(pred)
    return out


def _evaluate_pre_resolution_whale(engine: "AlertEngine") -> List[Dict[str, Any]]:
    """Join pending predictions with rugger risk on the same netuid (§32)."""
    pending = _pending_by_netuid()
    if not pending:
        return []
    created: List[Dict[str, Any]] = []
    try:
        from internal.ruggers.watchlist import RuggerWatchlist

        watch = RuggerWatchlist()
    except Exception:
        return []
    for netuid, preds in pending.items():
        risk = watch.get_subnet_risk(int(netuid)) or {}
        level = str(risk.get("risk_level") or "").lower()
        if level not in ("high", "medium"):
            continue
        pred = preds[0] if preds else {}
        pid = pred.get("id") or netuid
        alert = engine._append_alert(
            {
                "alert_type": "pre_resolution_whale",
                "severity": "warning" if level == "high" else "info",
                "message": f"SN{netuid}: open pick + {level} rug risk before resolution",
                "details": {"netuid": netuid, "risk_level": level, "prediction_id": pid},
                "dedupe_key": f"pre_res_whale_{netuid}_{pid}",
                "subnet_id": int(netuid),
                "threshold_type": "rug_risk",
            }
        )
        if alert:
            created.append(alert)
    return created


def run_conviction_evaluation(engine: "AlertEngine") -> Dict[str, Any]:
    """Evaluate conviction thresholds and create deduped alerts."""
    run_at = _utcnow_z()
    config = get_conviction_config()
    result: Dict[str, Any] = {
        "status": "ok",
        "last_run_at": run_at,
        "enabled": config["enabled"],
        "created": [],
        "created_count": 0,
        "candidates": 0,
        "skipped": 0,
    }

    if not config["enabled"]:
        result["reason"] = "disabled"
        _last_run.update({"last_run_at": run_at, "created": 0, "reason": "disabled"})
        return result

    min_conf = config["min_confidence"]
    candidates = _collect_candidates()
    result["candidates"] = len(candidates)
    created: List[Dict[str, Any]] = []

    for item in candidates:
        conf = float(item.get("confidence") or 0)
        if conf < min_conf:
            result["skipped"] += 1
            continue
        netuid = item.get("netuid")
        tier = item.get("tier", "cyan")
        name = item.get("name") or f"SN{netuid}"
        alert = engine._append_alert(
            {
                "alert_type": "conviction_threshold",
                "severity": "info" if tier == "gold" else "warning",
                "message": f"{name} conviction {conf:.0f}% ({tier} tier)",
                "details": {**item, "min_confidence": min_conf},
                "dedupe_key": f"conviction_{netuid}_{tier}",
                "subnet_id": int(netuid) if netuid is not None else None,
                "threshold_type": "conviction",
                "threshold_value": min_conf,
                "threshold_operator": "gte",
            }
        )
        if alert:
            created.append(alert)

    result["created"] = created
    result["created_count"] = len(created)

    pre_res = _evaluate_pre_resolution_whale(engine)
    if pre_res:
        result["pre_resolution_whale"] = pre_res
        result["created"].extend(pre_res)
        result["created_count"] = len(result["created"])

    try:
        from internal.conviction_alerts.delivery import deliver_alerts

        result["delivery"] = deliver_alerts(created)
    except Exception as exc:
        result["delivery"] = {"mode": "error", "error": str(exc)}
    _last_run.update(
        {
            "last_run_at": run_at,
            "created": len(created),
            "reason": "evaluated",
            "delivery": result.get("delivery"),
        }
    )
    return result


def get_last_run_status() -> Dict[str, Any]:
    return {
        **get_conviction_config(),
        "last_run": dict(_last_run),
    }
