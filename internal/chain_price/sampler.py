"""Forward chain price sampler tick (#1395 Step 0)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_client import PRICE_SCALE, _decode_scale_u64, _hex_to_bytes
from internal.chain_price import config as cfg
from internal.chain_price import db as price_db
from internal.chain_price.outcomes import RpcOutcome, TickOutcome, TickResult
from internal.chain_price.rpc import rpc_call_fn
from internal.disk_guard import data_free_bytes, is_low
from internal.chain_price.storage_keys import (
    map_key_hex,
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
    reserve_query_keys,
    timestamp_now_key_hex,
)

logger = logging.getLogger(__name__)

_KIND_FORWARD = "forward"
_consecutive_hard_failures = 0
_disk_low_last_log = 0.0
_DISK_LOW_LOG_INTERVAL_SECONDS = 600.0


def _bucket_ts_ms(ts_ms: int) -> int:
    bucket_ms = cfg.TICK_INTERVAL_SECONDS * 1000
    return (ts_ms // bucket_ms) * bucket_ms


def _parse_block_number(header: Dict[str, Any]) -> Optional[int]:
    num = header.get("number")
    if num is None:
        return None
    if isinstance(num, str):
        return int(num, 16)
    return int(num)


def _decode_u64_storage(raw: Any) -> Optional[int]:
    if raw is None or raw == "0x" or raw == "0x00":
        return None
    try:
        return _decode_scale_u64(_hex_to_bytes(raw))
    except (TypeError, ValueError):
        return None


def _fetch_networks_added(
    call: Callable[[str, list], Tuple[Optional[Any], RpcOutcome]],
    at_hash: str,
) -> Tuple[List[int], RpcOutcome]:
    prefix = networks_added_prefix_hex()
    netuids: List[int] = []
    start: Optional[str] = None
    while True:
        params = [prefix, 200, start, at_hash]
        page, outcome = call("state_getKeysPaged", params)
        if outcome != "ok":
            return netuids, outcome
        if not page:
            break
        for key in page:
            netuid = netuid_from_networks_added_key(key)
            if netuid != 0:
                netuids.append(netuid)
        if len(page) < 200:
            break
        start = page[-1]
    return sorted(set(netuids)), "ok"


def _parse_storage_batch(
    changes: List[List[Any]],
    netuids: List[int],
    block: int,
    provider: str,
    ts_ms: int,
    spot_by_netuid: Dict[int, float],
) -> Tuple[List[Dict[str, Any]], TickOutcome]:
    by_key: Dict[str, Optional[str]] = {row[0]: row[1] for row in changes if row}
    tao_key = {n: map_key_hex(b"SubnetTAO", n) for n in netuids}
    alpha_key = {n: map_key_hex(b"SubnetAlphaIn", n) for n in netuids}
    reg_key = {n: map_key_hex(b"NetworkRegisteredAt", n) for n in netuids}

    null_count = 0
    rows: List[Dict[str, Any]] = []
    for netuid in netuids:
        tao_raw = _decode_u64_storage(by_key.get(tao_key[netuid]))
        alpha_raw = _decode_u64_storage(by_key.get(alpha_key[netuid]))
        registered_at = _decode_u64_storage(by_key.get(reg_key[netuid]))
        if tao_raw is None or alpha_raw is None or alpha_raw == 0 or registered_at is None:
            null_count += 1
            continue
        price_tao = tao_raw / alpha_raw
        spot_raw = spot_by_netuid.get(netuid)
        spot_price_tao = spot_raw
        quality = "chain_sampled"
        if spot_price_tao is not None and price_tao > 0:
            rel = abs(spot_price_tao / price_tao - 1.0)
            if rel > cfg.SPOT_DIVERGENCE_MAX:
                quality = "disputed"
        rows.append(
            {
                "netuid": netuid,
                "block": block,
                "provider": provider,
                "ts_ms": ts_ms,
                "registered_at": registered_at,
                "tao_reserve_raw": tao_raw,
                "alpha_reserve_raw": alpha_raw,
                "price_tao": price_tao,
                "spot_price_tao": spot_price_tao,
                "unit": "tao",
                "quality": quality,
                "schema_version": cfg.SCHEMA_VERSION,
            }
        )

    if netuids and null_count / len(netuids) > cfg.SCHEMA_MISS_NULL_RATIO:
        return rows, "schema_miss"
    if not rows:
        return rows, "absent"
    return rows, "ok"


def _crosscheck_netuids(netuids: List[int], block: int) -> List[int]:
    if not netuids:
        return []
    ordered = sorted(netuids)
    idx = block % len(ordered)
    first = ordered[idx]
    second = ordered[(idx + 1) % len(ordered)]
    return [first, second]


def _spot_prices(
    call: Callable[[str, list], Tuple[Optional[Any], RpcOutcome]],
    netuids: List[int],
    at_hash: str,
) -> Tuple[Dict[int, float], int]:
    spots: Dict[int, float] = {}
    failures = 0
    for netuid in netuids:
        raw, outcome = call("swap_currentAlphaPrice", [netuid, at_hash])
        if outcome != "ok":
            failures += 1
            logger.warning(
                "chain price spot cross-check failed netuid=%s outcome=%s",
                netuid,
                outcome,
            )
            continue
        if raw is None:
            continue
        spots[netuid] = float(raw) / PRICE_SCALE
    if failures:
        logger.info(
            "chain price spot cross-check: %d/%d netuids failed",
            failures,
            len(netuids),
        )
    return spots, failures


def run_forward_sample(
    client: Any,
    *,
    db_path: Optional[str] = None,
    write: bool = True,
) -> TickResult:
    """Sample finalized head and persist chain prices when outcome is ``ok``."""
    global _consecutive_hard_failures

    if not cfg.forward_record_enabled():
        return {"outcome": "disabled"}

    if is_low(cfg.CHAIN_PRICE_MIN_FREE_MB):
        _log_disk_low_skip(cfg.CHAIN_PRICE_MIN_FREE_MB)
        try:
            from internal.metrics import CHAIN_PRICE_SKIPPED_TOTAL

            CHAIN_PRICE_SKIPPED_TOTAL.labels(reason="disk_low").inc()
        except Exception:
            pass
        return {"outcome": "disk_low"}

    price_db.ensure_schema(db_path)
    call = rpc_call_fn(client)

    block_hash, outcome = call("chain_getFinalizedHead", [])
    if outcome != "ok" or not block_hash:
        _bump_hard_failures(outcome)
        return {"outcome": outcome or "rpc_error"}

    header, outcome = call("chain_getHeader", [block_hash])
    if outcome != "ok" or not isinstance(header, dict):
        _bump_hard_failures(outcome)
        return {"outcome": outcome or "rpc_error"}

    block = _parse_block_number(header)
    if block is None:
        _bump_hard_failures("invalid")
        return {"outcome": "invalid", "error": "missing block number"}

    netuids, outcome = _fetch_networks_added(call, block_hash)
    if outcome != "ok":
        _bump_hard_failures(outcome)
        return {"outcome": outcome, "block": block, "block_hash": block_hash}

    query_keys = reserve_query_keys(netuids)
    batch, outcome = call("state_queryStorageAt", [query_keys, block_hash])
    if outcome != "ok" or not batch:
        _bump_hard_failures(outcome)
        return {"outcome": outcome or "rpc_error", "block": block, "block_hash": block_hash}

    changes = batch[0].get("changes") if isinstance(batch[0], dict) else None
    if not changes:
        _bump_hard_failures("absent")
        return {"outcome": "absent", "block": block, "block_hash": block_hash}

    ts_raw = None
    ts_key = timestamp_now_key_hex()
    for key, value in changes:
        if key == ts_key:
            ts_raw = value
            break
    ts_ms = _decode_u64_storage(ts_raw)
    if ts_ms is None:
        _bump_hard_failures("invalid")
        return {"outcome": "invalid", "error": "timestamp missing", "block": block}

    cross_netuids = _crosscheck_netuids(netuids, block)
    spot_by_netuid, spot_failures = _spot_prices(call, cross_netuids, block_hash)

    _, provider = cfg.primary_rpc_endpoint()
    rows, parse_outcome = _parse_storage_batch(
        changes, netuids, block, provider, ts_ms, spot_by_netuid
    )
    if parse_outcome != "ok":
        _bump_hard_failures(parse_outcome)
        return {
            "outcome": parse_outcome,
            "block": block,
            "block_hash": block_hash,
            "ts_ms": ts_ms,
            "n_subnets": len(netuids),
        }

    samples_written = 0
    if write:
        price_db.insert_block_row(
            provider=provider,
            block=block,
            block_hash=block_hash,
            ts_ms=ts_ms,
            bucket_ts=_bucket_ts_ms(ts_ms),
            kind=_KIND_FORWARD,
            n_subnets=len(netuids),
            path=db_path,
        )
        samples_written = price_db.insert_sample_rows(rows, path=db_path)
        price_db.prune_old_rows(path=db_path)

    _consecutive_hard_failures = 0
    result: TickResult = {
        "outcome": "ok",
        "provider": provider,
        "block": block,
        "block_hash": block_hash,
        "ts_ms": ts_ms,
        "n_subnets": len(netuids),
        "samples_written": samples_written,
    }
    if spot_failures:
        result["spot_crosscheck_failures"] = spot_failures
    return result


def _log_disk_low_skip(min_free_mb: int) -> None:
    global _disk_low_last_log
    now = time.time()
    if now - _disk_low_last_log < _DISK_LOW_LOG_INTERVAL_SECONDS:
        return
    _disk_low_last_log = now
    logger.warning(
        "chain price forward sample skipped: disk_low free_bytes=%s min_free_mb=%s",
        data_free_bytes(),
        min_free_mb,
    )


def _bump_hard_failures(outcome: TickOutcome | RpcOutcome | None) -> None:
    global _consecutive_hard_failures
    if outcome in ("rate_limited", "schema_miss"):
        _consecutive_hard_failures += 1
        if _consecutive_hard_failures >= cfg.MAX_CONSECUTIVE_HARD_FAILURES:
            logger.error(
                "chain price recorder: %d consecutive %s — cancel scheduler",
                _consecutive_hard_failures,
                outcome,
            )
            from internal.chain_price.scheduler import stop_forward_recorder

            stop_forward_recorder()
    else:
        _consecutive_hard_failures = 0


def sample_sn64_from_block(
    client: Any,
    block_hash: str,
    *,
    block_number: int = 9060887,
) -> Dict[str, Any]:
    """Offline helper: parse SN64 sample fields at a pinned block (fixture tests)."""
    call = rpc_call_fn(client)
    netuids, outcome = _fetch_networks_added(call, block_hash)
    if outcome != "ok" or 64 not in netuids:
        raise AssertionError(f"networks added failed: {outcome}")
    query_keys = reserve_query_keys(netuids)
    batch, outcome = call("state_queryStorageAt", [query_keys, block_hash])
    if outcome != "ok" or not batch:
        raise AssertionError(f"storage batch failed: {outcome}")
    changes = batch[0]["changes"]
    ts_ms = _decode_u64_storage(
        next(val for key, val in changes if key == timestamp_now_key_hex())
    )
    spot_raw, spot_outcome = call("swap_currentAlphaPrice", [64, block_hash])
    if spot_outcome != "ok":
        raise AssertionError(spot_outcome)
    spot_price_tao = float(spot_raw) / PRICE_SCALE
    _, provider = cfg.primary_rpc_endpoint()
    rows, parse_outcome = _parse_storage_batch(
        changes,
        netuids,
        block_number,
        provider,
        ts_ms or 0,
        {64: spot_price_tao},
    )
    if parse_outcome != "ok":
        raise AssertionError(parse_outcome)
    row = next(r for r in rows if r["netuid"] == 64)
    return {
        **row,
        "spot_raw": int(spot_raw),
        "ts_ms": ts_ms,
    }
