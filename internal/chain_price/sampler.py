"""Forward chain price sampler tick (#1395 Step 0/2)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from internal.chain_client import PRICE_SCALE, _decode_scale_u64, _hex_to_bytes
from internal.chain_price import config as cfg
from internal.chain_price import db as price_db
from internal.chain_price.bars import series_key
from internal.chain_price.membership import get_member_netuids
from internal.chain_price.outcomes import RpcOutcome, TickOutcome, TickResult
from internal.chain_price.reader import ChainReader
from internal.chain_rpc_errors import storage_block_matches
from internal.chain_price.storage_keys import (
    map_key_hex,
    reserve_query_keys,
    timestamp_now_key_hex,
)

logger = logging.getLogger(__name__)

_KIND_FORWARD = "forward"
_KIND_BACKFILL = "backfill"
_consecutive_schema_miss = 0
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


def _returned_block_matches(entry: Any, block_hash: str) -> bool:
    """Fail closed: a storage read must report the pinned block or nothing is persisted."""
    return storage_block_matches(entry, block_hash)


def _decode_u64_storage(raw: Any) -> Optional[int]:
    if raw is None or raw == "0x" or raw == "0x00":
        return None
    try:
        return _decode_scale_u64(_hex_to_bytes(raw))
    except (TypeError, ValueError):
        return None


def _parse_storage_batch(
    changes: List[List[Any]],
    netuids: List[int],
    block: int,
    block_hash: str,
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
        spot_price_tao = spot_by_netuid.get(netuid)
        quality = "chain_sampled"
        if spot_price_tao is not None and price_tao > 0:
            rel = abs(spot_price_tao / price_tao - 1.0)
            if rel > cfg.SPOT_DIVERGENCE_MAX:
                quality = "disputed"
        rows.append(
            {
                "netuid": netuid,
                "block": block,
                "block_hash": block_hash,
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
                "series_key": series_key(netuid, registered_at),
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
    call,
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


def sample_at_block_hash(
    reader: ChainReader,
    block_hash: str,
    block: int,
    *,
    write: bool = True,
    kind: str = _KIND_FORWARD,
    db_path: Optional[str] = None,
    bucket_ts_override: Optional[int] = None,
    bump_schema_miss_on_error: bool = True,
) -> TickResult:
    """Membership → reserves → spot cross-check → optional persist at a pinned block."""
    call = reader.call_fn()
    netuids, outcome = get_member_netuids(call, block_hash)
    if outcome != "ok":
        if bump_schema_miss_on_error:
            _bump_schema_miss(outcome)
        return {"outcome": outcome, "block": block, "block_hash": block_hash}

    query_keys = reserve_query_keys(netuids)
    batch, outcome = call("state_queryStorageAt", [query_keys, block_hash])
    if outcome != "ok" or not batch:
        if bump_schema_miss_on_error:
            _bump_schema_miss(outcome)
        return {"outcome": outcome or "rpc_error", "block": block, "block_hash": block_hash}

    storage_provider = reader.provider_served or cfg.primary_rpc_endpoint()[1]
    entry = batch[0] if isinstance(batch[0], dict) else {}
    if not _returned_block_matches(entry, block_hash):
        if bump_schema_miss_on_error:
            _bump_schema_miss("invalid")
        return {
            "outcome": "invalid",
            "error": "pinned block mismatch",
            "block": block,
            "block_hash": block_hash,
        }

    changes = entry.get("changes")
    if not changes:
        if bump_schema_miss_on_error:
            _bump_schema_miss("absent")
        return {"outcome": "absent", "block": block, "block_hash": block_hash}

    ts_raw = None
    ts_key = timestamp_now_key_hex()
    for key, value in changes:
        if key == ts_key:
            ts_raw = value
            break
    ts_ms = _decode_u64_storage(ts_raw)
    if ts_ms is None:
        if bump_schema_miss_on_error:
            _bump_schema_miss("invalid")
        return {"outcome": "invalid", "error": "timestamp missing", "block": block}

    cross_netuids = _crosscheck_netuids(netuids, block)
    spot_by_netuid, spot_failures = _spot_prices(call, cross_netuids, block_hash)

    provider = storage_provider
    rows, parse_outcome = _parse_storage_batch(
        changes, netuids, block, block_hash, provider, ts_ms, spot_by_netuid
    )
    if parse_outcome != "ok":
        if bump_schema_miss_on_error:
            _bump_schema_miss(parse_outcome)
        return {
            "outcome": parse_outcome,
            "block": block,
            "block_hash": block_hash,
            "ts_ms": ts_ms,
            "n_subnets": len(netuids),
        }

    bucket_ts = bucket_ts_override if bucket_ts_override is not None else _bucket_ts_ms(ts_ms)
    samples_written = 0
    if write:
        # Count only keys this batch adds: a rerun over stored rows inserts nothing new.
        new_rows = price_db.count_new_sample_rows(rows, path=db_path)
        if not price_db.can_accept_sample_batch(new_rows, path=db_path):
            return {
                "outcome": "row_cap_exceeded",
                "block": block,
                "block_hash": block_hash,
                "ts_ms": ts_ms,
                "n_subnets": len(netuids),
                "samples_written": 0,
            }
        price_db.insert_block_row(
            provider=provider,
            block=block,
            block_hash=block_hash,
            ts_ms=ts_ms,
            bucket_ts=bucket_ts,
            kind=kind,
            n_subnets=len(netuids),
            path=db_path,
        )
        samples_written = price_db.insert_sample_rows(rows, path=db_path)
        price_db.prune_old_rows(path=db_path)
        if kind == _KIND_BACKFILL and bucket_ts_override is not None:
            if not price_db.hourly_bucket_has_chain_sample(bucket_ts_override, path=db_path):
                return {
                    "outcome": "bucket_incomplete",
                    "block": block,
                    "block_hash": block_hash,
                    "ts_ms": ts_ms,
                    "n_subnets": len(netuids),
                    "samples_written": samples_written,
                    "error": "bucket incomplete: not every netuid has a chain_sampled row",
                }

    if bump_schema_miss_on_error:
        global _consecutive_schema_miss
        _consecutive_schema_miss = 0
    result: TickResult = {
        "outcome": "ok",
        "provider": provider,
        "provider_served": provider,
        "block": block,
        "block_hash": block_hash,
        "ts_ms": ts_ms,
        "n_subnets": len(netuids),
        "samples_written": samples_written,
    }
    if spot_failures:
        result["spot_crosscheck_failures"] = spot_failures
    return result


def run_forward_sample(
    client_or_reader: Any,
    *,
    db_path: Optional[str] = None,
    write: bool = True,
) -> TickResult:
    """Sample finalized head and persist chain prices when outcome is ``ok``."""
    global _consecutive_schema_miss

    if not cfg.forward_record_enabled():
        return {"outcome": "disabled"}

    reader = client_or_reader if isinstance(client_or_reader, ChainReader) else None
    if reader is None:
        reader = ChainReader([(cfg.primary_rpc_endpoint()[1], client_or_reader)])

    db_file = db_path or cfg.CHAIN_PRICE_DB_PATH
    from internal.disk_guard import db_disk_guard_outcome

    guard = db_disk_guard_outcome(db_file, cfg.CHAIN_PRICE_MIN_FREE_MB)
    if guard == "db_unavailable":
        logger.warning("chain price db unavailable: disk guard failed for %s", db_file)
        return {"outcome": "db_unavailable"}
    if guard == "disk_low":
        _log_disk_low_skip(cfg.CHAIN_PRICE_MIN_FREE_MB, db_file)
        try:
            from internal.metrics import CHAIN_PRICE_SKIPPED_TOTAL

            CHAIN_PRICE_SKIPPED_TOTAL.labels(reason="disk_low").inc()
        except Exception:
            pass
        return {"outcome": "disk_low"}

    try:
        price_db.ensure_schema(db_path)
    except OSError as exc:
        logger.warning("chain price db unavailable: %s", exc)
        return {"outcome": "db_unavailable"}

    try:
        call = reader.call_fn()
        block_hash, outcome = reader.pin_finalized_head()
        if outcome != "ok" or not block_hash:
            _bump_schema_miss(outcome)
            return {"outcome": outcome or "rpc_error"}

        header, outcome = call("chain_getHeader", [block_hash])
        if outcome != "ok" or not isinstance(header, dict):
            _bump_schema_miss(outcome)
            return {"outcome": outcome or "rpc_error"}

        block = _parse_block_number(header)
        if block is None:
            _bump_schema_miss("invalid")
            return {"outcome": "invalid", "error": "missing block number"}

        return sample_at_block_hash(
            reader,
            block_hash,
            block,
            write=write,
            kind=_KIND_FORWARD,
            db_path=db_path,
            bump_schema_miss_on_error=True,
        )
    finally:
        reader.reset_pin()


def _log_disk_low_skip(min_free_mb: int, db_file: str) -> None:
    global _disk_low_last_log
    now = time.time()
    if now - _disk_low_last_log < _DISK_LOW_LOG_INTERVAL_SECONDS:
        return
    _disk_low_last_log = now
    from internal.disk_guard import data_volume_usage_for_path

    directory = os.path.dirname(os.path.abspath(db_file)) or "."
    try:
        free = data_volume_usage_for_path(directory).free
    except OSError:
        free = -1
    logger.warning(
        "chain price forward sample skipped: disk_low free_bytes=%s min_free_mb=%s db_dir=%s",
        free,
        min_free_mb,
        directory,
    )


def _bump_schema_miss(outcome: TickOutcome | RpcOutcome | None) -> None:
    global _consecutive_schema_miss
    if outcome == "schema_miss":
        _consecutive_schema_miss += 1
        if _consecutive_schema_miss >= cfg.MAX_CONSECUTIVE_SCHEMA_MISS:
            logger.error(
                "chain price recorder: %d consecutive schema_miss — cancel scheduler",
                _consecutive_schema_miss,
            )
            from internal.chain_price.scheduler import stop_forward_recorder

            stop_forward_recorder()
    elif outcome not in ("rate_limited",):
        _consecutive_schema_miss = 0


def sample_sn64_from_block(
    client: Any,
    block_hash: str,
    *,
    block_number: int = 9060887,
) -> Dict[str, Any]:
    """Offline helper: parse SN64 sample fields at a pinned block (fixture tests)."""
    reader = ChainReader([(cfg.primary_rpc_endpoint()[1], client)])
    call = reader.call_fn()
    netuids, outcome = get_member_netuids(call, block_hash)
    if outcome != "ok" or 64 not in netuids:
        raise AssertionError(f"networks added failed: {outcome}")
    query_keys = reserve_query_keys(netuids)
    batch, outcome = call("state_queryStorageAt", [query_keys, block_hash])
    if outcome != "ok" or not batch:
        raise AssertionError(f"storage batch failed: {outcome}")
    if not _returned_block_matches(batch[0], block_hash):
        raise AssertionError("pinned block mismatch")
    storage_provider = reader.provider_served or cfg.primary_rpc_endpoint()[1]
    changes = batch[0]["changes"]
    ts_ms = _decode_u64_storage(
        next(val for key, val in changes if key == timestamp_now_key_hex())
    )
    spot_raw, spot_outcome = call("swap_currentAlphaPrice", [64, block_hash])
    if spot_outcome != "ok":
        raise AssertionError(spot_outcome)
    spot_price_tao = float(spot_raw) / PRICE_SCALE
    rows, parse_outcome = _parse_storage_batch(
        changes,
        netuids,
        block_number,
        block_hash,
        storage_provider,
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
