"""Caution Cells — rare downside posture (not a second buy scoreboard).

Solo fire: anticipated drawdown ≥6% (signal_impact or crash-tail).
Otherwise require 2+ stacked risk flags. Cap site-wide; never on Daily Call face.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

DRAWDOWN_SOLO_PCT = 6.0
MAX_CELLS = 3
SCAN_LIMIT = 8
SEEN_PATH = os.environ.get(
    "CAUTION_CELLS_SEEN_PATH", os.path.join("data", "caution_cells_seen.json")
)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_seen() -> Dict[str, List[str]]:
    try:
        with open(SEEN_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_seen(data: Dict[str, List[str]]) -> None:
    try:
        os.makedirs(os.path.dirname(SEEN_PATH) or ".", exist_ok=True)
        tmp = SEEN_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, SEEN_PATH)
    except Exception as exc:
        logger.warning("caution_cells seen persist failed: %s", exc)


def _already_flagged(netuid: int) -> bool:
    seen = _load_seen()
    return str(netuid) in (seen.get(_today()) or [])


def _mark_flagged(netuid: int) -> None:
    seen = _load_seen()
    day = _today()
    bucket = list(seen.get(day) or [])
    key = str(netuid)
    if key not in bucket:
        bucket.append(key)
    # Keep only today + yesterday
    pruned = {day: bucket}
    yday = list(seen.keys())
    for k in yday:
        if k != day and len(pruned) < 2:
            pruned[k] = seen[k]
    _save_seen(pruned)


def _call_netuid(daily_pick: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(daily_pick, dict):
        return None
    for key in ("pick", "candidate"):
        block = daily_pick.get(key)
        if isinstance(block, dict) and isinstance(block.get("subnet"), dict):
            try:
                return int(block["subnet"].get("netuid"))
            except (TypeError, ValueError):
                return None
    return None


def _scan_pool(subnets: List[Dict[str, Any]], call_nu: Optional[int]) -> List[Dict[str, Any]]:
    from internal.subnets.tradable import subnet_volume

    ranked = sorted(
        subnets,
        key=lambda s: subnet_volume(s),
        reverse=True,
    )
    out: List[Dict[str, Any]] = []
    seen: Set[int] = set()
    for sn in ranked:
        try:
            nu = int(sn.get("netuid", sn.get("id")))
        except (TypeError, ValueError):
            continue
        if call_nu is not None and nu == call_nu:
            continue
        if nu in seen:
            continue
        seen.add(nu)
        out.append(sn)
        if len(out) >= SCAN_LIMIT:
            break
    return out


def evaluate_subnet_caution(
    sn: Dict[str, Any],
    *,
    market_context: Optional[Dict[str, Any]] = None,
    fading: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return a caution cell dict or None."""
    try:
        nu = int(sn.get("netuid", sn.get("id")))
    except (TypeError, ValueError):
        return None
    if _already_flagged(nu):
        return None

    try:
        from internal.council.dark_horse_crash import crash_tail_features
        from internal.council.state_vector import score_subnet_for_day
        from internal.subnet_names import name_for_netuid

        score = score_subnet_for_day(sn, market_context or {})
    except Exception as exc:
        logger.warning("caution score failed for SN%s: %s", sn.get("netuid"), exc)
        return None

    si = score.get("signal_impact") if isinstance(score.get("signal_impact"), dict) else {}
    try:
        pred = float(si.get("net_predicted_pct") or 0)
    except (TypeError, ValueError):
        pred = 0.0
    features = crash_tail_features(sn)
    drawdown = float(features.get("drawdown_pct") or 0)
    dominant = str(si.get("dominant") or "")
    sell_active = dominant == "SELL ALERT"

    reasons: List[str] = []
    solo = False
    if pred <= -DRAWDOWN_SOLO_PCT:
        solo = True
        reasons.append(f"anticipated {pred:.1f}%")
    if drawdown <= -DRAWDOWN_SOLO_PCT:
        solo = True
        reasons.append(f"crash-tail {drawdown:.1f}%")

    stack = 0
    if sell_active:
        stack += 1
        reasons.append("distribution")
    if fading:
        stack += 1
        reasons.append("fading on table")
    # Yield trap as light risk flag
    if sn.get("yield_trap"):
        stack += 1
        reasons.append("yield trap")

    if not solo and stack < 2:
        return None
    if not reasons:
        return None

    name = name_for_netuid(nu) if nu is not None else sn.get("name") or f"SN{nu}"
    lead = reasons[0]
    detail = " · ".join(reasons[:3])
    cell = {
        "netuid": nu,
        "name": name,
        "label": "CAUTION",
        "line": f"Caution · {name} · {detail}",
        "reasons": reasons,
        "anticipated_pct": pred if pred < 0 else None,
        "solo": solo,
    }
    return cell


def build_caution_cells(
    subnets: List[Dict[str, Any]],
    *,
    daily_pick: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    fading_netuids: Optional[Set[int]] = None,
    limit: int = MAX_CELLS,
) -> List[Dict[str, Any]]:
    """Build up to ``limit`` caution cells; emit trail for new flags."""
    if not subnets:
        return []
    call_nu = _call_netuid(daily_pick)
    fading_netuids = fading_netuids or set()
    cells: List[Dict[str, Any]] = []
    for sn in _scan_pool(subnets, call_nu):
        try:
            nu = int(sn.get("netuid", sn.get("id")))
        except (TypeError, ValueError):
            continue
        cell = evaluate_subnet_caution(
            sn,
            market_context=market_context,
            fading=nu in fading_netuids,
        )
        if not cell:
            continue
        cells.append(cell)
        try:
            from internal.learning.trail_bus import emit_signal_triggered

            emit_signal_triggered(
                subnet=cell.get("name"),
                netuid=cell.get("netuid"),
                signal_name="caution_cell",
                direction="down",
                evidence={
                    "reasons": cell.get("reasons"),
                    "solo": cell.get("solo"),
                    "line": cell.get("line"),
                },
            )
            _mark_flagged(int(cell["netuid"]))
        except Exception as exc:
            logger.warning("caution trail failed: %s", exc)
        if len(cells) >= limit:
            break
    return cells
