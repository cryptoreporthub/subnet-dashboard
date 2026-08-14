"""Build explorable Mindmap node/edge graph from live trail + dispositions (read-only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_graph() -> Dict[str, Any]:
    from internal.learning.mindmap_aggregator import _build_integration_status, _build_runtime_status

    return {
        "status": "success",
        "source": "registry_heuristic",
        "nodes": [],
        "edges": [],
        "integration_status": _build_integration_status(),
        "runtime_status": _build_runtime_status(),
    }


# Pseudo-subnet hub for judge/weight-nudge events that carry no netuid — the
# loop tuning itself, not a specific subnet's evidence chain.
_LOOP_NODE_ID = "loop:council"


def _normalize_event_type(row: Dict[str, Any]) -> str:
    try:
        from internal.learning.trail_bus import normalize_event_type

        return str(normalize_event_type(row.get("event_type")) or "signal_triggered")
    except Exception:
        return str(row.get("event_type") or row.get("signal") or "signal_triggered")


def _load_dispositions() -> List[Dict[str, Any]]:
    try:
        from internal.store import get_dispositions

        rows = get_dispositions()
        if isinstance(rows, list) and rows:
            return [dict(r) for r in rows if isinstance(r, dict)]
    except Exception as exc:
        logger.debug("get_dispositions unavailable: %s", exc)

    try:
        from internal.council.weights import _load_raw

        sms = (_load_raw().get("soul_map_state") or {})
        out: List[Dict[str, Any]] = []
        decisions = (sms.get("last_selector_output") or {}).get("decisions") or []
        if isinstance(decisions, list):
            for row in decisions:
                if isinstance(row, dict) and row.get("netuid") is not None:
                    out.append(
                        {
                            "netuid": row.get("netuid"),
                            "action": row.get("recommended_action") or row.get("action") or "hold",
                            "score": row.get("score") or row.get("composite_score"),
                            "updated_at": row.get("updated_at") or sms.get("updated_at"),
                            "label": row.get("name"),
                        }
                    )
        for key in ("pump_dispositions", "message_intel_dispositions"):
            block = sms.get(key)
            if isinstance(block, dict):
                for netuid_key, payload in block.items():
                    if not isinstance(payload, dict):
                        continue
                    try:
                        netuid = int(netuid_key)
                    except (TypeError, ValueError):
                        netuid = payload.get("netuid")
                    if netuid is None:
                        continue
                    out.append(
                        {
                            "netuid": netuid,
                            "action": payload.get("recommended_action")
                            or payload.get("action")
                            or "hold",
                            "score": payload.get("score") or payload.get("composite_score"),
                            "updated_at": payload.get("updated_at") or sms.get("updated_at"),
                            "label": payload.get("name"),
                        }
                    )
        return out
    except Exception as exc:
        logger.warning("Soul-Map disposition fallback failed: %s", exc)
        return []


def _collect_trail(limit: int = 200) -> List[Dict[str, Any]]:
    from internal.learning.mindmap_aggregator import collect_trail_events

    trail = collect_trail_events(limit=limit)
    return [dict(row) for row in trail if isinstance(row, dict)]


def _load_indicator_alerts(focus_netuid: Optional[int]) -> List[Dict[str, Any]]:
    """RSI/MACD/momentum crossovers — read the engine's own persisted state
    directly rather than requiring indicators to push through the trail bus."""
    try:
        from internal.indicators.indicator_engine import IndicatorEngine

        alerts = IndicatorEngine().get_active_alerts()
    except Exception as exc:
        logger.debug("indicator alerts unavailable: %s", exc)
        return []
    if focus_netuid is not None:
        alerts = [a for a in alerts if a.get("subnet_id") == focus_netuid]
    return alerts


def _load_whale_and_rugger_alerts(focus_netuid: Optional[int]) -> Dict[str, List[Dict[str, Any]]]:
    """Whale/rugger desk alerts — same read-only approach as indicators."""
    try:
        from internal.whales.service import WhaleIntelligenceService

        alerts = WhaleIntelligenceService().get_active_alerts()
    except Exception as exc:
        logger.debug("whale/rugger alerts unavailable: %s", exc)
        return {"rugger_alerts": [], "follow_alerts": []}
    if focus_netuid is not None:
        alerts = {
            key: [a for a in rows if a.get("netuid") == focus_netuid]
            for key, rows in alerts.items()
            if isinstance(rows, list)
        }
    return alerts


def _subnet_label(netuid: Any, name: Optional[str], labels: Dict[Any, str]) -> str:
    if name:
        return str(name)
    if netuid in labels and labels[netuid]:
        return labels[netuid]
    if netuid is not None:
        return f"SN{netuid}"
    return "unknown"


def _upsert_node(
    nodes: Dict[str, Dict[str, Any]],
    node_id: str,
    *,
    label: str,
    kind: str,
    metrics: Optional[Dict[str, Any]] = None,
    updated_at: Optional[str] = None,
) -> None:
    existing = nodes.get(node_id)
    payload = {
        "id": node_id,
        "label": label,
        "kind": kind,
        "metrics": metrics or {},
        "updated_at": updated_at or _utcnow_z(),
    }
    if existing is None:
        nodes[node_id] = payload
        return
    existing_metrics = dict(existing.get("metrics") or {})
    existing_metrics.update(payload["metrics"])
    existing["metrics"] = existing_metrics
    if updated_at and (not existing.get("updated_at") or updated_at > existing.get("updated_at", "")):
        existing["updated_at"] = updated_at
    if label and existing.get("label") in {None, "", "unknown", f"SN{node_id.split(':')[-1]}"}:
        existing["label"] = label


def _append_edge(
    edges: List[Dict[str, Any]],
    seen: Set[Tuple[str, str, str]],
    *,
    source: str,
    target: str,
    kind: str,
    weight: float,
) -> None:
    key = (source, target, kind)
    if key in seen:
        return
    seen.add(key)
    edges.append(
        {
            "source": source,
            "target": target,
            "kind": kind,
            "weight": float(weight),
        }
    )


def _trail_matches_netuid(row: Dict[str, Any], focus: int) -> bool:
    nu = row.get("netuid")
    if nu is not None:
        try:
            if int(nu) == focus:
                return True
        except (TypeError, ValueError):
            pass
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    pl_nu = payload.get("netuid")
    if pl_nu is not None:
        try:
            return int(pl_nu) == focus
        except (TypeError, ValueError):
            return False
    return False


def get_mindmap_graph(focus_netuid: Optional[int] = None) -> Dict[str, Any]:
    """Return node/edge graph for interactive Mindmap UI (never raises).

    Intentionally does **not** call ``build_mindmap_state()`` — that runs every
    panel summary + ``select_hourly_pick`` (full-universe scoring) and wedged
    prod on cold ``GET /api/mindmap/graph``. Graph only needs trail +
    ``integration_status``; full state stays on ``/api/mindmap/state``.
    """
    try:
        trail = _collect_trail()
    except Exception as exc:
        logger.warning("mindmap graph trail read failed: %s", exc)
        return _empty_graph()

    if focus_netuid is not None:
        try:
            focus = int(focus_netuid)
            trail = [r for r in trail if _trail_matches_netuid(r, focus)]
            dispositions = [
                d
                for d in _load_dispositions()
                if d.get("netuid") is not None and int(d["netuid"]) == focus
            ]
        except (TypeError, ValueError):
            dispositions = _load_dispositions()
    else:
        dispositions = _load_dispositions()

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    edge_seen: Set[Tuple[str, str, str]] = set()
    subnet_stats: Dict[Any, Dict[str, Any]] = {}
    subnet_names: Dict[Any, str] = {}

    for row in trail:
        netuid = row.get("netuid")
        event_type = _normalize_event_type(row)
        event_time = str(row.get("time") or row.get("created_at") or "")
        subnet_name = row.get("subnet")

        _upsert_node(
            nodes,
            f"signal:{event_type}",
            label=event_type.replace("_", " ").title(),
            kind="signal",
            updated_at=event_time or None,
        )

        # Hub for this row: a real subnet when we have a netuid, otherwise the
        # learning loop's own self-adjustment. Judge/weight-nudge events (most
        # `weight_change`/`accuracy_update`/`conviction_update` rows) usually
        # aren't about any one subnet, but they're still the loop tuning
        # itself and deserve a home instead of being silently dropped.
        if netuid is not None:
            stats = subnet_stats.setdefault(
                netuid,
                {"event_count": 0, "last_event_type": event_type, "updated_at": event_time},
            )
            stats["event_count"] = int(stats.get("event_count", 0)) + 1
            if event_time >= str(stats.get("updated_at") or ""):
                stats["last_event_type"] = event_type
                stats["updated_at"] = event_time
            if subnet_name:
                subnet_names[netuid] = str(subnet_name)

            hub_id = f"subnet:{netuid}"
            _upsert_node(
                nodes,
                hub_id,
                label=_subnet_label(netuid, subnet_name, subnet_names),
                kind="subnet",
                metrics={
                    "event_count": stats["event_count"],
                    "last_event_type": stats["last_event_type"],
                },
                updated_at=stats.get("updated_at"),
            )
        else:
            hub_id = _LOOP_NODE_ID
            _upsert_node(nodes, hub_id, label="Learning Loop", kind="loop", updated_at=event_time or None)

        _append_edge(
            edges,
            edge_seen,
            source=hub_id,
            target=f"signal:{event_type}",
            kind=event_type,
            weight=1.0,
        )

        judge = row.get("judge")
        if judge:
            judge_id = f"judge:{judge}"
            _upsert_node(
                nodes,
                judge_id,
                label=str(judge).replace("_", " ").title(),
                kind="judge",
                updated_at=event_time or None,
            )
            _append_edge(
                edges,
                edge_seen,
                source=hub_id,
                target=judge_id,
                kind="judge_signal",
                weight=1.0,
            )

        if netuid is None:
            continue

        subnet_id = hub_id

        if row.get("prediction") or row.get("event_type") == "prediction_resolved":
            pred_id = f"prediction:{netuid}:{row.get('time') or len(edges)}"
            _upsert_node(
                nodes,
                pred_id,
                label=str(row.get("prediction") or "prediction")[:48],
                kind="prediction",
                metrics={"decision": row.get("decision")},
                updated_at=event_time or None,
            )
            _append_edge(
                edges,
                edge_seen,
                source=subnet_id,
                target=pred_id,
                kind="prediction",
                weight=1.0,
            )

        if row.get("event_type") == "scenario_tagged" or (row.get("evidence") or {}).get("regime"):
            scen_id = f"scenario:{netuid}:{(row.get('evidence') or {}).get('scenario_id', 'tag')}"
            _upsert_node(
                nodes,
                scen_id,
                label=str((row.get("evidence") or {}).get("regime") or "scenario"),
                kind="scenario",
                updated_at=event_time or None,
            )
            _append_edge(
                edges,
                edge_seen,
                source=subnet_id,
                target=scen_id,
                kind="scenario",
                weight=1.0,
            )

    for disp in dispositions:
        netuid = disp.get("netuid")
        if netuid is None:
            continue
        action = str(disp.get("action") or "hold").lower()
        # Graph taste: skip generic holds unless focus-scoped (ego still useful)
        if focus_netuid is None and action in ("hold", "neutral", "none", ""):
            continue
        score_raw = disp.get("score")
        try:
            weight = float(score_raw) if score_raw is not None else 1.0
        except (TypeError, ValueError):
            weight = 1.0
        updated_at = str(disp.get("updated_at") or _utcnow_z())
        label = _subnet_label(netuid, disp.get("label"), subnet_names)

        subnet_id = f"subnet:{netuid}"
        disp_id = f"disp:{netuid}"

        if subnet_id not in nodes:
            _upsert_node(
                nodes,
                subnet_id,
                label=label,
                kind="subnet",
                metrics={"event_count": 0, "last_event_type": None},
                updated_at=updated_at,
            )

        _upsert_node(
            nodes,
            disp_id,
            label=f"{label} · {action}",
            kind="disposition",
            metrics={"action": action, "score": score_raw},
            updated_at=updated_at,
        )

        _append_edge(
            edges,
            edge_seen,
            source=subnet_id,
            target=disp_id,
            kind="disposition",
            weight=weight,
        )

    # Whale / rugger / indicator desks track their own subnets already — read
    # them directly instead of asking three more subsystems to push through
    # the trail bus (they're never wrong about the netuid, so this is honest).
    for alert in _load_indicator_alerts(focus_netuid):
        netuid = alert.get("subnet_id")
        if netuid is None:
            continue
        event_type = str(alert.get("event_type") or "indicator_signal")
        subnet_id = f"subnet:{netuid}"
        if subnet_id not in nodes:
            _upsert_node(
                nodes,
                subnet_id,
                label=_subnet_label(netuid, None, subnet_names),
                kind="subnet",
                metrics={"event_count": 0, "last_event_type": None},
                updated_at=_utcnow_z(),
            )
        indicator_id = f"indicator:{netuid}:{event_type}"
        _upsert_node(
            nodes,
            indicator_id,
            label=event_type.replace("_", " ").title(),
            kind="indicator",
            updated_at=_utcnow_z(),
        )
        _append_edge(edges, edge_seen, source=subnet_id, target=indicator_id, kind=event_type, weight=1.0)

    whale_alerts = _load_whale_and_rugger_alerts(focus_netuid)
    for alert in whale_alerts.get("rugger_alerts") or []:
        netuid = alert.get("netuid")
        if netuid is None:
            continue
        subnet_id = f"subnet:{netuid}"
        if subnet_id not in nodes:
            _upsert_node(
                nodes,
                subnet_id,
                label=_subnet_label(netuid, alert.get("subnet_name"), subnet_names),
                kind="subnet",
                metrics={"event_count": 0, "last_event_type": None},
                updated_at=_utcnow_z(),
            )
        risk_id = f"risk:{netuid}:{alert.get('wallet') or 'w'}"
        _upsert_node(
            nodes,
            risk_id,
            label="Rugger exit warning",
            kind="risk",
            metrics={
                "urgency": alert.get("urgency"),
                "estimated_exit_in_hours": alert.get("estimated_exit_in_hours"),
            },
            updated_at=str(alert.get("entry_ts") or _utcnow_z()),
        )
        _append_edge(edges, edge_seen, source=subnet_id, target=risk_id, kind="rugger_exit_warning", weight=1.0)

    for alert in whale_alerts.get("follow_alerts") or []:
        netuid = alert.get("netuid")
        if netuid is None:
            continue
        subnet_id = f"subnet:{netuid}"
        if subnet_id not in nodes:
            _upsert_node(
                nodes,
                subnet_id,
                label=_subnet_label(netuid, alert.get("subnet_name"), subnet_names),
                kind="subnet",
                metrics={"event_count": 0, "last_event_type": None},
                updated_at=_utcnow_z(),
            )
        whale_id = f"whale:{netuid}:{alert.get('wallet') or 'w'}"
        _upsert_node(
            nodes,
            whale_id,
            label="Smart money entry",
            kind="whale",
            metrics={
                "win_rate": alert.get("win_rate"),
                "avg_return_pct": alert.get("avg_return_pct"),
            },
            updated_at=str(alert.get("entry_ts") or _utcnow_z()),
        )
        _append_edge(edges, edge_seen, source=subnet_id, target=whale_id, kind="smart_money_entry", weight=1.0)

    node_list = list(nodes.values())
    # Cap unscoped graphs — keep highest-degree nodes (readable ego clusters)
    _NODE_CAP = 48
    if focus_netuid is None and len(node_list) > _NODE_CAP:
        degree: Dict[str, int] = {}
        for e in edges:
            s, t = str(e.get("source")), str(e.get("target"))
            degree[s] = degree.get(s, 0) + 1
            degree[t] = degree.get(t, 0) + 1
        kind_boost = {
            "loop": 4,
            "judge": 3,
            "prediction": 2,
            "signal": 2,
            "risk": 2,
            "whale": 1,
            "indicator": 1,
            "scenario": 1,
            "disposition": 1,
            "subnet": 0,
        }
        node_list.sort(
            key=lambda n: (
                -(degree.get(str(n.get("id")), 0) + kind_boost.get(str(n.get("kind")), 0)),
                str(n.get("id")),
            )
        )
        keep_ids = {n["id"] for n in node_list[:_NODE_CAP]}
        node_list = [n for n in node_list if n["id"] in keep_ids]
        edges = [e for e in edges if e.get("source") in keep_ids and e.get("target") in keep_ids]

    from internal.learning.mindmap_aggregator import _build_integration_status, _build_runtime_status

    try:
        integration_status = _build_integration_status()
    except Exception as exc:
        logger.warning("mindmap integration_status failed: %s", exc)
        integration_status = {}
    try:
        runtime_status = _build_runtime_status()
    except Exception as exc:
        logger.warning("mindmap runtime_status failed: %s", exc)
        runtime_status = {}

    return {
        "status": "success",
        "source": "registry_heuristic",
        "focus_netuid": focus_netuid,
        "scoped": focus_netuid is not None,
        "nodes": node_list,
        "edges": edges,
        "integration_status": integration_status,
        "runtime_status": runtime_status,
    }
