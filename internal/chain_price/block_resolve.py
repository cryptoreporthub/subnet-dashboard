"""Resolve chain block number/hash from wall-clock ms (#1395 Step 2)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Literal, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.reader import ChainReader

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 4
_MAX_ROUNDS_BRACKETED = 18
_TOLERANCE_MS = 12_000
_NOMINAL_BLOCK_MS = 12_000
_BLOCK_CACHE: Dict[int, Tuple[str, int]] = {}
SearchMode = Literal["stepped", "bracketed"]


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


def _probe_block_ts(
    call,
    reader: ChainReader,
    block: int,
    low: int,
    high: int,
) -> Tuple[Optional[int], Optional[str], Optional[int], RpcOutcome]:
    block = max(low, min(high, block))
    if block in _BLOCK_CACHE:
        block_hash, block_ts = _BLOCK_CACHE[block]
        return block, block_hash, block_ts, "ok"
    block_hash, outcome = call("chain_getBlockHash", [block])
    if outcome != "ok" or not block_hash:
        return None, None, None, outcome
    header, outcome = call("chain_getHeader", [block_hash])
    if outcome != "ok" or not isinstance(header, dict):
        return None, None, None, outcome
    block_ts, ts_outcome = _block_ts_via_reader(reader, block_hash)
    if ts_outcome != "ok" or block_ts is None:
        return None, None, None, ts_outcome
    _BLOCK_CACHE[block] = (block_hash, block_ts)
    return block, block_hash, block_ts, "ok"


def _resolve_stepped(
    call,
    reader: ChainReader,
    ts_ms: int,
    low: int,
    high: int,
    *,
    hint_block: Optional[int],
    max_rounds: int,
) -> Tuple[Optional[int], Optional[str], RpcOutcome]:
    block = hint_block if hint_block is not None else high
    block = max(low, min(high, block))
    block_hash: Optional[str] = None

    for _round in range(max_rounds):
        block, block_hash, block_ts, outcome = _probe_block_ts(call, reader, block, low, high)
        if outcome != "ok" or block_ts is None or block_hash is None:
            return None, None, outcome
        delta = block_ts - ts_ms
        if abs(delta) <= _TOLERANCE_MS:
            return block, block_hash, "ok"
        step = round(-delta / _NOMINAL_BLOCK_MS) or (-1 if delta > 0 else 1)
        block = max(low, min(high, block + step))

    return None, None, "invalid"


def _target_inside_stall_gap(probed: Dict[int, int], ts_ms: int) -> bool:
    """True when ``ts_ms`` lies strictly between two consecutive probed blocks' timestamps."""
    if len(probed) < 2:
        return False
    ordered = sorted(probed.items())
    for (b_lo, t_lo), (b_hi, t_hi) in zip(ordered, ordered[1:]):
        if b_hi != b_lo + 1:
            continue
        if t_lo < ts_ms < t_hi:
            return True
    return False


def _bracket_blocks(probed_ts: Dict[int, int], ts_ms: int, low: int, high: int) -> Tuple[int, int]:
    below = [b for b, t in probed_ts.items() if t <= ts_ms]
    above = [b for b, t in probed_ts.items() if t >= ts_ms]
    low_b = max(below) if below else low
    high_b = min(above) if above else high
    return max(low, low_b), min(high, high_b)


def _resolve_bracketed(
    call,
    reader: ChainReader,
    ts_ms: int,
    low: int,
    high: int,
    *,
    hint_block: Optional[int],
    anchor_blocks: Iterable[int],
    max_rounds: int,
) -> Tuple[Optional[int], Optional[str], RpcOutcome]:
    probed_ts: Dict[int, int] = {}

    block_n, block_hash, head_ts, outcome = _probe_block_ts(call, reader, high, low, high)
    if outcome != "ok" or head_ts is None or block_hash is None:
        return None, None, outcome
    probed_ts[block_n] = head_ts
    if abs(head_ts - ts_ms) <= _TOLERANCE_MS:
        return block_n, block_hash, "ok"
    if head_ts < ts_ms:
        return None, None, "invalid"

    est = high + round((ts_ms - head_ts) / _NOMINAL_BLOCK_MS)
    seeds = [max(low, min(high, est))]
    if hint_block is not None:
        seeds.append(hint_block)
    seeds.extend(anchor_blocks)

    for block in seeds:
        block_n, block_hash, block_ts, outcome = _probe_block_ts(call, reader, block, low, high)
        if outcome != "ok" or block_ts is None or block_hash is None:
            return None, None, outcome
        probed_ts[block_n] = block_ts
        if abs(block_ts - ts_ms) <= _TOLERANCE_MS:
            return block_n, block_hash, "ok"

    low_b, high_b = _bracket_blocks(probed_ts, ts_ms, low, high)

    for _round in range(max_rounds):
        if _target_inside_stall_gap(probed_ts, ts_ms):
            return None, None, "invalid"
        if high_b <= low_b:
            break
        mid = (low_b + high_b) // 2
        block_n, block_hash, block_ts, outcome = _probe_block_ts(call, reader, mid, low, high)
        if outcome != "ok" or block_ts is None or block_hash is None:
            return None, None, outcome
        probed_ts[block_n] = block_ts
        if abs(block_ts - ts_ms) <= _TOLERANCE_MS:
            return block_n, block_hash, "ok"
        low_b, high_b = _bracket_blocks(probed_ts, ts_ms, low, high)

    return None, None, "invalid"


def resolve_block_at(
    reader: ChainReader,
    ts_ms: int,
    *,
    hint_block: Optional[int] = None,
    search: SearchMode = "stepped",
    max_rounds: Optional[int] = None,
    anchor_blocks: Optional[Iterable[int]] = None,
) -> Tuple[Optional[int], Optional[str], RpcOutcome]:
    """Resolve block number/hash for wall-clock ``ts_ms`` within ``_TOLERANCE_MS``.

    ``stepped`` (default): estimate-and-correct, ≤4 rounds — forward recorder latency path.
    ``bracketed``: anchored bisection with a higher round budget for historical backfill.
    """
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
    rounds = max_rounds
    if rounds is None:
        rounds = _MAX_ROUNDS_BRACKETED if search == "bracketed" else _MAX_ROUNDS

    if search == "bracketed":
        return _resolve_bracketed(
            call,
            reader,
            ts_ms,
            low,
            high,
            hint_block=hint_block,
            anchor_blocks=anchor_blocks or (),
            max_rounds=rounds,
        )
    return _resolve_stepped(
        call, reader, ts_ms, low, high, hint_block=hint_block, max_rounds=rounds
    )


def clear_block_cache() -> None:
    _BLOCK_CACHE.clear()
