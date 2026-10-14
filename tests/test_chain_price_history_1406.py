"""Historical-spec replay for #1395 Step 2 (Replit finding 4 on PR #1406).

Fixtures were recorded read-only from Blockmachine at pinned blocks (runtime spec in brackets):
  bm_9064796.json  [455] ~30 days back: SN64 sample, NetworksAdded, SN92 first registration
  bm_9273596.json  [477] SN64 sample, NetworksAdded, SN92 re-registered
  bm_9280796.json  [478] SN64 sample, NetworksAdded, SN92 re-registered
  bm_9247818.json  NetworksAdded only: SN92 absent between its two registrations
Replay raises on any key not recorded, and logs every call so pinned-hash use can be asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.chain_price.membership import get_member_netuids
from internal.chain_price.sampler import _parse_storage_batch, sample_sn64_from_block
from internal.chain_price.storage_keys import reserve_query_keys

FIX = Path(__file__).parent / "fixtures" / "chain"
H_9064796 = "0xfb6be3e19d6febbac1dc7da6957d15dca869a11abc3c25f7cb33ceab151ff8e0"
H_9273596 = "0x90001c6794e5f73c69b129623441435375620f3375126e6baa799bf5708e783b"
H_9280796 = "0x72a82add74d481216a2f4b8f77e7729f88b2abf0654a9c6be89a3cf10f7cedd0"

# Expected values were printed at record time and pinned here; the parser must reproduce them.
SN64_EXPECTED = {
    "bm_9064796.json": dict(
        block_hash=H_9064796, tao=200406512340818, alpha=2884890524907085,
        price=0.06946763165207892, ts_ms=1789375968000,
    ),
    "bm_9273596.json": dict(
        block_hash=H_9273596, tao=200835810443564, alpha=2935190424113945,
        price=0.06842343474331514, ts_ms=1791885768000,
    ),
    "bm_9280796.json": dict(
        block_hash=H_9280796, tao=200558208509125, alpha=2941160431132601,
        price=0.06819016276235321, ts_ms=1791972168001,
    ),
}


class _Replay:
    def __init__(self, name: str):
        self.data = json.loads((FIX / name).read_text())
        self.calls: list[tuple[str, list]] = []

    def _respond(self, method, params=None):
        params = params or []
        self.calls.append((method, params))
        key = f"{method}|{json.dumps(params)}"
        if key not in self.data:
            raise RuntimeError(f"not recorded: {key[:100]}")
        return self.data[key]

    def _call_typed(self, method, params=None):
        return self._respond(method, params)

    def _call(self, method, params=None):
        return self._respond(method, params)

    def query_storage_at(self, keys, at_hash):
        return self._respond("state_queryStorageAt", [keys, at_hash])


def _membership(replay, block_hash):
    netuids, outcome = get_member_netuids(lambda m, p: (replay._call_typed(m, p), "ok"), block_hash)
    assert outcome == "ok"
    return netuids


@pytest.mark.parametrize("fixture", sorted(SN64_EXPECTED))
def test_sn64_decodes_to_recorded_values(fixture):
    exp = SN64_EXPECTED[fixture]
    replay = _Replay(fixture)
    row = sample_sn64_from_block(replay, exp["block_hash"])
    assert row["tao_reserve_raw"] == exp["tao"]
    assert row["alpha_reserve_raw"] == exp["alpha"]
    assert row["ts_ms"] == exp["ts_ms"]
    assert row["registered_at"] == 4531295
    assert row["price_tao"] == pytest.approx(exp["price"], rel=1e-12)


@pytest.mark.parametrize("fixture", sorted(SN64_EXPECTED))
def test_sn64_price_matches_recorded_chain_spot(fixture):
    # Independent of the reserve parser: the recorded swap_currentAlphaPrice answer at the same block.
    exp = SN64_EXPECTED[fixture]
    replay = _Replay(fixture)
    spot_raw = replay.data[f"swap_currentAlphaPrice|{json.dumps([64, exp['block_hash']])}"]
    row = sample_sn64_from_block(replay, exp["block_hash"])
    assert abs(row["price_tao"] - spot_raw / 1e9) / (spot_raw / 1e9) < 1e-6


def test_every_pinned_call_carries_the_requested_hash():
    exp = SN64_EXPECTED["bm_9280796.json"]
    replay = _Replay("bm_9280796.json")
    sample_sn64_from_block(replay, exp["block_hash"])
    pinned = [(m, p) for m, p in replay.calls if m.startswith(("state_", "swap_"))]
    assert pinned, "no pinned calls recorded"
    for method, params in pinned:
        assert params[-1] == exp["block_hash"], method


def test_sn92_absent_between_registrations_and_lineage_changes_across_them():
    gap = _Replay("bm_9247818.json")
    assert 92 not in _membership(gap, _hash_for(gap, 9247818))
    assert 64 in _membership(gap, _hash_for(gap, 9247818))

    first = _Replay("bm_9064796.json")
    second = _Replay("bm_9280796.json")
    reg_first = _registered_at(first, H_9064796, 92)
    reg_second = _registered_at(second, H_9280796, 92)
    assert reg_first == 8352006
    assert reg_second == 9247819
    assert reg_second != reg_first  # a different series_key, so the two lifetimes never join
    assert reg_second > 9247818  # registered after the absence block


def _hash_for(replay, block):
    return replay.data[f"chain_getBlockHash|{json.dumps([block])}"]


def _registered_at(replay, block_hash, netuid):
    netuids = _membership(replay, block_hash)
    batch = replay._call_typed("state_queryStorageAt", [reserve_query_keys(netuids), block_hash])
    rows, outcome = _parse_storage_batch(
        batch[0]["changes"], netuids, 0, block_hash, "blockmachine", 0, {}
    )
    assert outcome == "ok"
    return next(r["registered_at"] for r in rows if r["netuid"] == netuid)


def test_unrecorded_block_hash_fails_instead_of_using_head():
    replay = _Replay("bm_9273596.json")
    with pytest.raises(AssertionError):
        sample_sn64_from_block(replay, "0x" + "11" * 32)
