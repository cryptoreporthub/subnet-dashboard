"""Gather live signal features for pump ladder classification."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _subnet_netuids_from_entities(entities: Any) -> List[int]:
    if not isinstance(entities, dict):
        return []
    out: List[int] = []
    for token in entities.get("subnets") or []:
        for num in re.findall(r"\d+", str(token)):
            try:
                out.append(int(num))
            except ValueError:
                continue
    return out


def message_intel_chatter_by_netuid() -> Dict[int, float]:
    """Map netuid → normalized chatter intensity from persisted message-intel."""
    counts: Dict[int, int] = {}
    try:
        from internal.message_intel.store import get_db

        db = get_db()
        with db._connect() as conn:
            rows = conn.execute(
                """SELECT ma.entities_json, v.conviction
                   FROM messages m
                   JOIN message_analysis ma ON ma.message_id = m.id
                   LEFT JOIN message_verdicts v ON v.message_id = m.id
                   ORDER BY m.id DESC LIMIT 200"""
            ).fetchall()
        import json

        for row in rows:
            try:
                entities = json.loads(row["entities_json"] or "{}")
            except Exception:
                entities = {}
            conviction = float(row["conviction"] or 0) / 100.0
            for netuid in _subnet_netuids_from_entities(entities):
                counts[netuid] = counts.get(netuid, 0) + 1 + conviction
    except Exception as exc:
        logger.debug("message-intel chatter unavailable: %s", exc)

    if not counts:
        return {}
    peak = max(counts.values()) or 1.0
    return {k: round(v / peak, 4) for k, v in counts.items()}


def scenario_tags_by_netuid() -> Dict[int, str]:
    """Recent scenario-memory tags keyed by netuid when present in features."""
    tags: Dict[int, str] = {}
    try:
        from internal.analytics.scenario_state import load_scenario_snapshot

        snap = load_scenario_snapshot()
        for row in snap.get("scenarios") or []:
            features = row.get("features") or {}
            netuid = features.get("netuid")
            if netuid is None:
                continue
            try:
                tags[int(netuid)] = str(row.get("name") or row.get("outcome") or "tagged")
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        logger.debug("scenario tags unavailable: %s", exc)
    return tags


def build_subnet_signals(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize TaoMarketCap subnet row into ladder classifier inputs."""
    netuid = subnet.get("netuid")
    price_change = float(subnet.get("price_change_24h") or subnet.get("change_24h") or 0)
    volume = float(subnet.get("volume") or 0)
    buy = float(subnet.get("buy_volume_24h") or 0)
    sell = float(subnet.get("sell_volume_24h") or 0)
    flow_total = buy + sell
    buy_ratio = (buy / flow_total) if flow_total > 0 else 0.5

    chatter_map = message_intel_chatter_by_netuid()
    scenario_map = scenario_tags_by_netuid()
    chatter = float(chatter_map.get(int(netuid), 0)) if netuid is not None else 0.0
    scenario_tag = scenario_map.get(int(netuid)) if netuid is not None else None

    # Volume spike proxy: scale 24h volume against emission (activity per unit stake).
    emission = float(subnet.get("emission") or 1.0) or 1.0
    volume_intensity = min(volume / (emission * 1000.0 + 1.0), 3.0) / 3.0

    momentum_1h = float(subnet.get("price_change_1h") or price_change / 24.0)

    return {
        "netuid": netuid,
        "name": subnet.get("name") or f"SN{netuid}",
        "price_change_24h": price_change,
        "momentum_1h": momentum_1h,
        "volume_intensity": round(volume_intensity, 4),
        "buy_ratio": round(buy_ratio, 4),
        "chatter_intensity": chatter,
        "scenario_tag": scenario_tag,
        "emission": emission,
    }


def fetch_all_subnet_signals() -> List[Dict[str, Any]]:
    try:
        from fetchers.taomarketcap import get_all_subnets

        subnets = get_all_subnets() or []
        return [build_subnet_signals(s) for s in subnets if s.get("netuid") is not None]
    except Exception as exc:
        logger.warning("subnet signal fetch failed: %s", exc)
        return []
