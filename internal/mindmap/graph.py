"""Build explorable Mindmap node/edge graph from live trail + dispositions (read-only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_graph() -> Dict[str, Any]:
    return {"status": "success", "nodes": [], "edges": []}


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


def get_mindmap_graph() -> Dict[str, Any]:
    """Return node/edge graph for interactive Mindmap UI (never raises)."""
    try:
        from internal.learning.mindmap_aggregator import build_mindmap_state

        state = build_mindmap_state()
        trail = state.get("trail") or _collect_trail()
    except Exception as exc:
        logger.warning("mindmap graph state read failed: %s", exc)
        try:
            trail = _collect_trail()
            state = {}
        except Exception:
            return _empty_graph()

    if not trail:
        trail = _collect_trail()

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

        if netuid is None:
            continue

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

        subnet_id = f"subnet:{netuid}"
        label = _subnet_label(netuid, subnet_name, subnet_names)
        _upsert_node(
            nodes,
            subnet_id,
            label=label,
            kind="subnet",
            metrics={
                "event_count": stats["event_count"],
                "last_event_type": stats["last_event_type"],
            },
            updated_at=stats.get("updated_at"),
        )

        _append_edge(
            edges,
            edge_seen,
            source=subnet_id,
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
                source=subnet_id,
                target=judge_id,
                kind="judge_signal",
                weight=1.0,
            )

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
        action = str(disp.get("action") or "hold")
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

    return {
        "status": "success",
        "nodes": list(nodes.values()),
        "edges": edges,
    }
