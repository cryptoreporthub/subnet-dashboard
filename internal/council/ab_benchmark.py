"""Evidence-first comparison of the Daily Model and Judge Council rankings.

This module deliberately records both lists before either one becomes the
homepage hero.  It is a small research ledger, not a second prediction loop:
the background pick refresh supplies one shared subnet universe and one market
snapshot per observation slot, while this module records the two ranking
systems side by side.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from internal.subnets.tradable import tradable_subnets

logger = logging.getLogger(__name__)

AB_BENCHMARK_PATH = os.environ.get(
    "AB_BENCHMARK_PATH", os.path.join("data", "council_ab_benchmark.json")
)
AB_BENCHMARK_TOP_N = max(2, int(os.environ.get("AB_BENCHMARK_TOP_N", "5")))
AB_BENCHMARK_HORIZON_HOURS = max(
    1, int(os.environ.get("AB_BENCHMARK_HORIZON_HOURS", "24"))
)
AB_BENCHMARK_INTERVAL_MINUTES = max(
    15, min(int(os.environ.get("AB_BENCHMARK_INTERVAL_MINUTES", "180")), 24 * 60)
)
AB_BENCHMARK_MINIMUM_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_data() -> Dict[str, Any]:
    return {"version": 1, "horizon_hours": AB_BENCHMARK_HORIZON_HOURS, "snapshots": []}


def _load(path: Optional[str] = None) -> Dict[str, Any]:
    try:
        with open(path or AB_BENCHMARK_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("horizon_hours", AB_BENCHMARK_HORIZON_HOURS)
            data.setdefault("snapshots", [])
            return data
    except Exception:
        pass
    return _default_data()


def _save(data: Dict[str, Any], path: Optional[str] = None) -> None:
    target = path or AB_BENCHMARK_PATH
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, target)


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _netuid(row: Dict[str, Any]) -> Optional[int]:
    try:
        raw = row.get("netuid", row.get("id"))
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _price(row: Dict[str, Any]) -> Optional[float]:
    value = _number(row.get("price"))
    return value if value is not None and value > 0 else None


def _research_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the scalar context that explains a ranking without storing feeds."""
    out: Dict[str, Any] = {}
    for key in ("tao_change_24h", "gainers", "losers", "breadth", "volatility"):
        if key in context:
            value = context.get(key)
            out[key] = _number(value) if key not in ("breadth",) else str(value)
    weights = context.get("weights")
    if isinstance(weights, dict):
        out["weights"] = {
            str(key): _number(value)
            for key, value in weights.items()
            if _number(value) is not None
        }
    return out


def _daily_rankings(
    subnets: List[Dict[str, Any]], market_context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    from internal.council.state_vector import score_subnet_for_day

    scored: List[Dict[str, Any]] = []
    for subnet in subnets:
        try:
            score = score_subnet_for_day(subnet, market_context)
            scored.append(
                {
                    "netuid": _netuid(subnet),
                    "name": subnet.get("name") or f"SN{_netuid(subnet)}",
                    "score": _number(score.get("total_score")) or 0.0,
                    "confidence": _number(score.get("confidence")),
                    "direction": "long",
                    "entry_price": _price(subnet),
                }
            )
        except Exception as exc:
            logger.debug("A/B daily score skipped for %s: %s", _netuid(subnet), exc)
    scored.sort(key=lambda row: (row["score"], row["netuid"] or -1), reverse=True)
    return [{**row, "rank": index} for index, row in enumerate(scored[:AB_BENCHMARK_TOP_N], 1)]


def _judge_rankings(
    subnets: List[Dict[str, Any]], market_context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    from internal.judges.subnet_judges import score_all_subnets

    scored = score_all_subnets(subnets, market_context=market_context, use_chain=False)
    rows: List[Dict[str, Any]] = []
    for row in scored:
        consensus = row.get("consensus") or {}
        verdict = str(consensus.get("verdict") or "neutral").lower()
        rows.append(
            {
                "netuid": _netuid(row),
                "name": row.get("name") or f"SN{_netuid(row)}",
                "score": _number(consensus.get("score")) or 0.0,
                "agreement": _number(consensus.get("agreement")),
                "confidence": _number(consensus.get("confidence")),
                "verdict": verdict,
                "direction": (
                    "long"
                    if verdict in ("long", "bullish")
                    else "short"
                    if verdict in ("short", "bearish")
                    else "neutral"
                ),
                "entry_price": _price(
                    next(
                        (subnet for subnet in subnets if _netuid(subnet) == _netuid(row)),
                        {},
                    )
                ),
                "judge_scores": {
                    key: _number((row.get(key) or {}).get("score"))
                    for key in ("oracle", "echo", "pulse")
                },
            }
        )
    rows.sort(key=lambda row: (row["score"], row["netuid"] or -1), reverse=True)
    return [{**row, "rank": index} for index, row in enumerate(rows[:AB_BENCHMARK_TOP_N], 1)]


def _snapshot_slot(captured_at: str) -> str:
    """Return the fixed UTC observation slot for an ISO timestamp."""
    parsed = _parse_iso(captured_at)
    if parsed is None:
        return captured_at
    interval_seconds = AB_BENCHMARK_INTERVAL_MINUTES * 60
    slot_epoch = int(parsed.timestamp()) // interval_seconds * interval_seconds
    return datetime.fromtimestamp(slot_epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def record_snapshot(
    subnets: Iterable[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    *,
    captured_at: Optional[str] = None,
    source: str = "pick-refresh-scheduler",
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one immutable A/B observation.

    A fixed UTC slot is written only once.  This prevents a retry, changed
    price feed, or homepage request from rewriting the research sample while
    still capturing dynamic ranking changes throughout the day.
    """
    captured = captured_at or _now_iso()
    rows = tradable_subnets([dict(row) for row in (subnets or []) if isinstance(row, dict)])
    data = _load(path)
    snapshots = [row for row in data.get("snapshots", []) if isinstance(row, dict)]
    observation_slot = _snapshot_slot(captured)
    existing = next(
        (
            row
            for row in snapshots
            if row.get("observation_slot") == observation_slot
            or (
                not row.get("observation_slot")
                and row.get("captured_at") == captured
            )
        ),
        None,
    )
    if existing:
        return existing

    context = dict(market_context or {})
    snapshot = {
        "date": captured[:10],
        "captured_at": captured,
        "observation_slot": observation_slot,
        "interval_minutes": AB_BENCHMARK_INTERVAL_MINUTES,
        "source": source,
        "horizon_hours": AB_BENCHMARK_HORIZON_HOURS,
        "universe_count": len(rows),
        "universe_netuids": [_netuid(row) for row in rows if _netuid(row) is not None],
        "market_context": _research_context(context),
        "daily_model": _daily_rankings(rows, context),
        "judge_council": _judge_rankings(rows, context),
        "status": "open",
    }
    snapshots.append(snapshot)
    snapshots.sort(key=lambda row: str(row.get("captured_at") or ""))
    data["snapshots"] = snapshots
    _save(data, path)
    return snapshot


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _return_for(entry: Any, exit_price: Any, direction: str) -> Optional[float]:
    start = _number(entry)
    finish = _number(exit_price)
    if start is None or finish is None or start <= 0:
        return None
    raw = (finish - start) / start
    if direction == "short":
        raw *= -1
    if direction == "neutral":
        return 0.0
    return round(raw, 6)


def _settle_rows(
    rows: List[Dict[str, Any]], current_by_netuid: Dict[int, Dict[str, Any]], settled_at: str
) -> int:
    changed = 0
    for row in rows:
        if row.get("result") is not None:
            continue
        netuid = _netuid(row)
        current = current_by_netuid.get(netuid) if netuid is not None else None
        exit_price = _price(current or {})
        result = _return_for(row.get("entry_price"), exit_price, str(row.get("direction") or "neutral"))
        if result is None:
            continue
        row["exit_price"] = exit_price
        row["settled_at"] = settled_at
        row["return_pct"] = round(result * 100.0, 4)
        row["result"] = "neutral" if row.get("direction") == "neutral" else ("hit" if result > 0 else "miss")
        changed += 1
    return changed


def settle_due_snapshots(
    subnets: Iterable[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Settle snapshots once their fixed horizon has elapsed."""
    current_time = now or datetime.now(timezone.utc)
    current_rows = [dict(row) for row in (subnets or []) if isinstance(row, dict)]
    current_by_netuid = {
        _netuid(row): row for row in current_rows if _netuid(row) is not None
    }
    data = _load(path)
    changed = 0
    for snapshot in data.get("snapshots", []):
        if not isinstance(snapshot, dict) or snapshot.get("status") == "settled":
            continue
        captured = _parse_iso(snapshot.get("captured_at"))
        if not captured or current_time < captured + timedelta(hours=AB_BENCHMARK_HORIZON_HOURS):
            continue
        settled_at = current_time.isoformat().replace("+00:00", "Z")
        changed += _settle_rows(snapshot.get("daily_model") or [], current_by_netuid, settled_at)
        changed += _settle_rows(snapshot.get("judge_council") or [], current_by_netuid, settled_at)
        all_rows = (snapshot.get("daily_model") or []) + (snapshot.get("judge_council") or [])
        snapshot["status"] = "settled" if all(row.get("result") is not None for row in all_rows) else "partial"
        snapshot["settled_at"] = settled_at
    if changed:
        _save(data, path)
    return data


def _model_metrics(snapshots: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    rows = [
        row
        for snapshot in snapshots
        for row in (snapshot.get(key) or [])
        if isinstance(row, dict) and row.get("result") in ("hit", "miss", "neutral")
    ]
    directional = [row for row in rows if row.get("direction") in ("long", "short")]
    returns = [_number(row.get("return_pct")) for row in directional]
    returns = [value for value in returns if value is not None]
    hits = sum(1 for row in directional if row.get("result") == "hit")
    return {
        "settled_entries": len(rows),
        "directional_entries": len(directional),
        "hit_rate": round(hits / len(directional), 4) if directional else None,
        "equal_weight_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "best_return_pct": round(max(returns), 4) if returns else None,
        "worst_return_pct": round(min(returns), 4) if returns else None,
    }


def comparison(
    *,
    limit: int = 14,
    subnets: Optional[Iterable[Dict[str, Any]]] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    data = _load(path)
    if subnets is not None:
        data = settle_due_snapshots(subnets, path=path)
    all_snapshots = [row for row in data.get("snapshots", []) if isinstance(row, dict)]
    all_snapshots.sort(key=lambda row: str(row.get("captured_at") or ""))
    snapshots = all_snapshots[-max(1, min(int(limit), 90)) :]
    settled_snapshots = [row for row in all_snapshots if row.get("status") == "settled"]
    observations_per_day = max(
        1, (24 * 60 + AB_BENCHMARK_INTERVAL_MINUTES - 1) // AB_BENCHMARK_INTERVAL_MINUTES
    )
    minimum_recommended_snapshots = AB_BENCHMARK_MINIMUM_DAYS * observations_per_day
    return {
        "status": "ok",
        "research_ready": len(settled_snapshots) >= minimum_recommended_snapshots,
        "minimum_recommended_days": AB_BENCHMARK_MINIMUM_DAYS,
        "minimum_recommended_snapshots": minimum_recommended_snapshots,
        "observation_interval_minutes": AB_BENCHMARK_INTERVAL_MINUTES,
        "observation_count": len(all_snapshots),
        "settled_observation_count": len(settled_snapshots),
        "observation_day_count": len({str(row.get("date")) for row in all_snapshots if row.get("date")}),
        "horizon_hours": AB_BENCHMARK_HORIZON_HOURS,
        "snapshot_count": len(all_snapshots),
        "daily_model": _model_metrics(all_snapshots, "daily_model"),
        "judge_council": _model_metrics(all_snapshots, "judge_council"),
        "snapshots": snapshots,
        "note": (
            f"Early comparison — {len(settled_snapshots)} of at least "
            f"{minimum_recommended_snapshots} observations have settled. "
            f"{len(all_snapshots)} immutable observations across "
            f"{len({str(row.get('date')) for row in all_snapshots if row.get('date')})} day(s). "
            f"Observations are captured every {AB_BENCHMARK_INTERVAL_MINUTES} minutes "
            "because the rankings are dynamic."
            if len(settled_snapshots) < minimum_recommended_snapshots
            else "Historical comparison uses immutable recurring observations and a shared 24h horizon."
        ),
    }