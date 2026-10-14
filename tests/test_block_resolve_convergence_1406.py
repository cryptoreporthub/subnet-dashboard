"""resolve_block_at converges within its round cap (#1406 follow-up to Replit's #1395 review).

The synthetic chain has 12s blocks with +/-1s jitter, a 500k-block window, and an optional
68-minute stall (a single block gap). Bisection over the window could not reach the 12s tolerance
in 4 rounds; the timestamp-corrected search must, including right after the stall.
"""

from __future__ import annotations

import random

import pytest

from internal.chain_price.block_resolve import clear_block_cache, resolve_block_at
from internal.chain_price.storage_keys import timestamp_now_key_hex

HEAD = 9_280_796
HEAD_TS_MS = 1_791_972_168_001
WINDOW = 500_000
STALL_BLOCK = HEAD - 100_000
STALL_MS = 68 * 60_000


class _SyntheticChain:
    """Serves the reader surface resolve_block_at uses: call / call_fn."""

    def __init__(self, stall_at: int | None = None, *, seed: int = 7, jitter: int = 1000):
        rng = random.Random(seed)
        self.ts = {HEAD: HEAD_TS_MS}
        cur = HEAD_TS_MS
        for n in range(HEAD - 1, HEAD - WINDOW - 1, -1):
            step = 12_000 + rng.randint(-jitter, jitter)
            if n == stall_at:
                step += STALL_MS
            cur -= step
            self.ts[n] = cur
        self._key = timestamp_now_key_hex()

    @staticmethod
    def _hash(n: int) -> str:
        return "0x%064x" % n

    # Pristine resolve_block_at reads timestamps through reader.active_client(); serving them here lets
    # the test reach the exit path it is meant to check, so a failure reflects the result, not the fake.
    def active_client(self):
        return self

    def get_block_ts_ms(self, block_hash):
        return self.ts[int(block_hash, 16)]

    def call(self, method, params):
        if method == "chain_getFinalizedHead":
            return self._hash(HEAD), "ok"
        if method == "chain_getHeader":
            return {"number": hex(int(params[0], 16))}, "ok"
        if method == "chain_getBlockHash":
            return self._hash(int(params[0])), "ok"
        if method == "state_queryStorageAt":
            n = int(params[1], 16)
            raw = self.ts[n].to_bytes(8, "little").hex()
            return [{"block": params[1], "changes": [[self._key, "0x" + raw]]}], "ok"
        raise AssertionError(f"unexpected method {method}")

    def call_fn(self):
        return self.call


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_block_cache()
    yield
    clear_block_cache()


@pytest.fixture(scope="module")
def plain_chain():
    return _SyntheticChain()


@pytest.fixture(scope="module")
def stalled_chain():
    return _SyntheticChain(stall_at=STALL_BLOCK)


@pytest.mark.parametrize("offset", [None, 0, 3, 1000])
def test_converges_for_target_inside_uniform_range(plain_chain, offset):
    target = HEAD - 123_456
    hint = None if offset is None else target + offset
    blk, bh, outcome = resolve_block_at(plain_chain, plain_chain.ts[target] + 2_000, hint_block=hint)
    assert outcome == "ok"
    assert abs(blk - target) <= 1
    assert bh == plain_chain._hash(blk)


@pytest.mark.parametrize("target", [STALL_BLOCK - 50, STALL_BLOCK, STALL_BLOCK + 1, STALL_BLOCK + 50])
@pytest.mark.parametrize("offset", [None, 0, 3])
def test_converges_on_either_side_of_the_stall(stalled_chain, target, offset):
    hint = None if offset is None else target + offset
    blk, _, outcome = resolve_block_at(stalled_chain, stalled_chain.ts[target], hint_block=hint)
    assert outcome == "ok"
    assert abs(blk - target) <= 1


def test_exhausted_search_never_returns_an_unprobed_block_with_a_stale_hash():
    # seed 6 / jitter 3000 with no stall exhausts _MAX_ROUNDS at this target (sweep: 1 of 3000 cases).
    # The old exit returned the clamped next step paired with the previous probe's hash.
    chain = _SyntheticChain(seed=6, jitter=3000)
    target = 9_081_136
    blk, bh, outcome = resolve_block_at(chain, chain.ts[target] + 2_000)
    assert outcome == "invalid"
    assert (blk, bh) == (None, None)


def test_target_inside_the_stall_gap_is_not_resolved(stalled_chain):
    lo, hi = stalled_chain.ts[STALL_BLOCK], stalled_chain.ts[STALL_BLOCK + 1]
    for ts_ms in ((lo + hi) // 2, lo + (hi - lo) // 10, hi - (hi - lo) // 10):
        clear_block_cache()
        _, _, outcome = resolve_block_at(stalled_chain, ts_ms)
        assert outcome != "ok"
