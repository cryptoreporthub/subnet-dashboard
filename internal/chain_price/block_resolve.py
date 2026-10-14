"""Resolve chain block number/hash from wall-clock ms (#1395 Step 2)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.reader import ChainReader

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 4
_TOLERANCE_MS = 12_000
_BLOCK_CACHE: Dict[int, Tuple[str, int]] = {}


def _header_block_number(header: Dict[str, Any]) -> Optional[int]:
    num = header.get("number")
    if num is None:
        return None
    if isinstance(num, str):
        return int(num, 16)
    return int(num)


def resolve_block_at(
    reader: ChainReader,
    ts_ms: int,
    *,
    hint_block: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str], RpcOutcome]:
    """Binary search with ≤4 refinement rounds and 12s timestamp tolerance."""
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
    block_ts: Optional[int] = None

    for _round in range(_MAX_ROUNDS):
        block_hash, outcome = call("chain_getBlockHash", [block])
        if outcome != "ok" or not block_hash:
            return None, None, outcome
        header, outcome = call("chain_getHeader", [block_hash])
        if outcome != "ok" or not isinstance(header, dict):
            return None, None, outcome
        client = reader.active_client()
        if client is None:
            return None, None, "rpc_error"
        try:
            block_ts = client.get_block_ts_ms(block_hash)
        except Exception:
            block_ts = None
        if block_ts is None:
            return None, None, "invalid"
        _BLOCK_CACHE[block] = (block_hash, block_ts)
        delta = block_ts - ts_ms
        if abs(delta) <= _TOLERANCE_MS:
            return block, block_hash, "ok"
        if delta > 0:
            high = block - 1
        else:
            low = block + 1
        if low > high:
            break
        block = (low + high) // 2

    if block_hash and block_ts is not None and abs(block_ts - ts_ms) <= _TOLERANCE_MS:
        return block, block_hash, "ok"
    return block, block_hash, "invalid"


def clear_block_cache() -> None:
    _BLOCK_CACHE.clear()
