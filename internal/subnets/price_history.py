"""Local alpha price history from Blockmachine sync samples.

Records price on each live_subnets sync and computes price_change_* without TMC.
ponytail: JSON file store — upgrade path is SQLite or reuse volume_cache.db.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RETENTION_DAYS = 35
_WINDOWS = (
    ("price_change_24h", 24),
    ("price_change_7d", 24 * 7),
    ("price_change_30d", 24 * 30),
)


def _data_dir() -> str:
    data_dir = os.environ.get("DATA_DIR", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(_REPO_ROOT, data_dir)
    return data_dir


def history_path() -> str:
    return os.path.join(_data_dir(), "alpha_price_history.json")


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _netuid_of(row: Dict[str, Any]) -> Optional[int]:
    for key in ("netuid", "id", "subnet_id"):
        val = row.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None


def _load_store() -> Dict[str, Any]:
    path = history_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"version": 1, "subnets": {}}


def _save_store(store: Dict[str, Any]) -> None:
    path = history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(store, handle)
    os.replace(tmp, path)


def _prune_samples(samples: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    cutoff = now - timedelta(days=_RETENTION_DAYS)
    kept: List[Dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        ts = _parse_ts(str(sample.get("ts") or ""))
        price = sample.get("price")
        if ts is None or price in (None, ""):
            continue
        try:
            float(price)
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            kept.append({"ts": ts.isoformat(), "price": float(price)})
    kept.sort(key=lambda s: s["ts"])
    return kept


def record_sync_samples(
    rows: List[Dict[str, Any]],
    *,
    synced_at: Optional[str] = None,
) -> None:
    """Append BM price samples from a live_subnets sync."""
    now = _parse_ts(synced_at) if synced_at else datetime.now(timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    store = _load_store()
    subnets = store.setdefault("subnets", {})
    if not isinstance(subnets, dict):
        subnets = {}
        store["subnets"] = subnets

    for row in rows:
        netuid = _netuid_of(row)
        if netuid is None:
            continue
        try:
            price = float(row.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        key = str(netuid)
        entry = subnets.get(key) or {"samples": []}
        samples = _prune_samples(list(entry.get("samples") or []), now)
        if samples and samples[-1]["ts"][:16] == now.isoformat()[:16]:
            samples[-1] = {"ts": now.isoformat(), "price": price}
        else:
            samples.append({"ts": now.isoformat(), "price": price})
        subnets[key] = {"samples": samples}
    store["updated_at"] = now.isoformat()
    _save_store(store)


def _lookup_price(
    samples: List[Dict[str, Any]],
    target: datetime,
) -> Optional[float]:
    if not samples:
        return None
    best: Optional[Tuple[float, float]] = None
    for sample in samples:
        ts = _parse_ts(sample["ts"])
        if ts is None:
            continue
        delta = abs((ts - target).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, float(sample["price"]))
    if best is None:
        return None
    # Reject matches more than 6h from target — history too sparse.
    if best[0] > 6 * 3600:
        return None
    return best[1]


def compute_price_changes(
    netuid: int,
    *,
    now: Optional[datetime] = None,
    store: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[float]]:
    """Return percent changes for 24h / 7d / 30d windows."""
    now = now or datetime.now(timezone.utc)
    data = store if store is not None else _load_store()
    entry = (data.get("subnets") or {}).get(str(netuid)) or {}
    samples = list(entry.get("samples") or [])
    if not samples:
        return {field: None for field, _hours in _WINDOWS}

    latest = _lookup_price(samples, now)
    if latest is None or latest <= 0:
        return {field: None for field, _hours in _WINDOWS}

    out: Dict[str, Optional[float]] = {}
    for field, hours in _WINDOWS:
        past = _lookup_price(samples, now - timedelta(hours=hours))
        if past is None or past <= 0:
            out[field] = None
        else:
            out[field] = round((latest - past) / past * 100.0, 4)
    return out


def _market_cap_proxy(row: Dict[str, Any]) -> float:
    try:
        price = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0
    if price <= 0:
        return 0.0
    for key in ("total_alpha", "liquidity", "total_stake", "stake"):
        try:
            mult = float(row.get(key) or 0)
        except (TypeError, ValueError):
            mult = 0.0
        if mult > 0:
            return price * mult
    return price


def _assign_ranks(rows: List[Dict[str, Any]]) -> None:
    ranked = sorted(
        ((i, _market_cap_proxy(row)) for i, row in enumerate(rows)),
        key=lambda item: item[1],
        reverse=True,
    )
    for rank, (idx, mcap) in enumerate(ranked, start=1):
        if mcap <= 0:
            continue
        rows[idx]["market_cap"] = round(mcap, 4)
        rows[idx]["marketcap_rank"] = rank
        rows[idx]["marketcap_rank_source"] = "bm_proxy"


def enrich_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach computed price_change_* and derived rank/mcap when missing."""
    if not rows:
        return rows
    store = _load_store()
    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        netuid = _netuid_of(merged)
        if netuid is not None:
            changes = compute_price_changes(netuid, now=now, store=store)
            for field, value in changes.items():
                if value is not None and merged.get(field) in (None, "", 0):
                    merged[field] = value
                    merged[f"{field}_source"] = "bm_history"
        out.append(merged)
    _assign_ranks(out)
    return out


if __name__ == "__main__":
    # ponytail: runnable self-check
    store = {
        "subnets": {
            "1": {
                "samples": [
                    {"ts": "2026-09-01T00:00:00+00:00", "price": 100.0},
                    {"ts": "2026-09-24T00:00:00+00:00", "price": 110.0},
                    {"ts": "2026-09-25T00:00:00+00:00", "price": 121.0},
                ]
            }
        }
    }
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    chg = compute_price_changes(1, now=now, store=store)
    assert chg["price_change_24h"] is not None
    assert chg["price_change_24h"] > 0
    rows = enrich_rows([{"netuid": 1, "price": 121.0, "total_alpha": 1000}])
    assert rows[0].get("marketcap_rank") == 1
    print("price_history self-check OK")
