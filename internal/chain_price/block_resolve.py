"""Resolve chain block number/hash from wall-clock ms (#1395 Step 2)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.reader import ChainReader

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 4
_TOLERANCE_MS = 12_000
_NOMINAL_BLOCK_MS = 12_000
_BLOCK_CACHE: Dict[int, Tuple[str, int]] = {}


def _header_block_number(header: Dict[str, Any]) -> Optional[int]:
    num = header.get("number")
    if num is None:
        return None
    if isinstance(num, str):
        return int(num, 16)
    return int(num)


def _block_ts_via_reader(reader: ChainReader, block_hash: str) -> Tuple[Optional[int], RpcOutcome]:
    """``Timestamp.Now`` at a pinned block, decoded the same way the sampler decodes it."""
    from internal.chain_price.sampler import _decode_u64_storage, _returned_block_matches
    from internal.chain_price.storage_keys import timestamp_now_key_hex

    key = timestamp_now_key_hex()
    batch, outcome = reader.call("state_queryStorageAt", [[key], block_hash])
    if outcome != "ok" or not batch:
        return None, outcome
    if not _returned_block_matches(batch[0], block_hash):
        return None, "invalid"
    for row_key, value in batch[0].get("changes") or []:
        if row_key == key:
            ts = _decode_u64_storage(value)
            return ts, ("ok" if ts is not None else "invalid")
    return None, "invalid"


def resolve_block_at(
    reader: ChainReader,
    ts_ms: int,
    *,
    hint_block: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str], RpcOutcome]:
    """Estimate-and-correct search: each probed timestamp moves the next probe, ≤4 rounds, 12s tolerance."""
    if hint_block is not None and hint_block in _BLOCK_CACHE:
        h, t = _BLOCK_CACHE[hint_block]
        if abs(t - ts_ms) <= _TOLERANCE_MS:
            return hint_block, h, "ok"

    call = reader.call_fn()
    head_hash, outcome = call("chain_getFinalizedHead", [])
    if outcome != "ok" or not head_hash:
        return None, None, outcome
    header, outcome = call("chain_getHeader", [head_hash])
    if outcome != "ok" or not isinstance(header, dict):
        return None, None, outcome
    high = _header_block_number(header)
    if high is None:
        return None, None, "invalid"

    low = max(0, high - 500_000)
    block = hint_block if hint_block is not None else high
    block = max(low, min(high, block))
    block_hash: Optional[str] = None

    for _round in range(_MAX_ROUNDS):
        block_hash, outcome = call("chain_getBlockHash", [block])
        if outcome != "ok" or not block_hash:
            return None, None, outcome
        header, outcome = call("chain_getHeader", [block_hash])
        if outcome != "ok" or not isinstance(header, dict):
            return None, None, outcome
        # Read the timestamp through the reader so a provider failure falls back like every other read.
        block_ts, ts_outcome = _block_ts_via_reader(reader, block_hash)
        if ts_outcome != "ok" or block_ts is None:
            return None, None, ts_outcome
        _BLOCK_CACHE[block] = (block_hash, block_ts)
        delta = block_ts - ts_ms
        if abs(delta) <= _TOLERANCE_MS:
            return block, block_hash, "ok"
        # Correct by the probed timestamp rather than bisecting the whole window: bisection
        # cannot reach a 12s tolerance in 4 rounds over a 500k-block range. A fixed 12s step
        # is wrong across a stall, but the next probe re-measures and corrects it.
        step = round(-delta / _NOMINAL_BLOCK_MS) or (-1 if delta > 0 else 1)
        block = max(low, min(high, block + step))

    # Exhausted without a verified probe. Returning ``block`` here would pair the
    # unprobed step with the previous probe's hash, so return no pair at all.
    return None, None, "invalid"


def clear_block_cache() -> None:
    _BLOCK_CACHE.clear()
