"""Stake-alert logic: Substrate primitives, diff/accumulate, formatting."""

from __future__ import annotations

import pytest

from internal.message_intel import stake_alert as sa


def test_xxh64_canonical_vectors():
    assert sa.xxh64(b"") == 0xEF46DB3751D8E999
    assert sa.xxh64(b"abc") == 0x44BC2CF5AD770999


def test_twox128_matches_live_node_prefix():
    # twox128("SubtensorModule") read back from a live Subtensor node
    assert sa.twox128(b"SubtensorModule").hex() == "658faa385070e074c85bf6b568cf0555"


def test_ss58_roundtrip_and_checksum():
    addr = sa.DEFAULT_HOTKEY
    pub = sa.ss58_to_pubkey(addr)
    assert len(pub) == 32
    assert sa.pubkey_to_ss58(pub) == addr
    bad = addr[:-3] + ("1" if addr[-3] != "1" else "2") + addr[-2:]
    with pytest.raises(ValueError):
        sa.ss58_to_pubkey(bad)


def test_alpha_storage_prefix_shape():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    prefix = sa.alpha_storage_prefix("Alpha", pub)
    assert prefix.startswith(sa.twox128(b"SubtensorModule") + sa.twox128(b"Alpha"))
    assert prefix.endswith(sa._blake2_concat(pub))


def test_decode_alpha_key_roundtrip():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    prefix = sa.alpha_storage_prefix("Alpha", pub)
    ck = bytes(range(32))
    key = prefix + sa._blake2_concat(ck) + (7).to_bytes(2, "little")
    assert sa._decode_alpha_key(key, len(prefix)) == (ck.hex(), 7)


def test_decode_value_u64f64():
    # Alpha map: U64F64 fixed point — stake rao in the high half
    assert sa._decode_value("0x000000000000000000e1f50500000000") == 100_000_000


def test_decode_value_safe_float():
    # AlphaV2 map: SafeFloat mantissa×10^exp, captured from a live node read
    raw = "0x00a85a21bf83f23a0c00000000000000f6ffffffffffffff"
    mantissa = int.from_bytes(bytes.fromhex("00a85a21bf83f23a0c00000000000000"), "little")
    assert sa._decode_value(raw) == mantissa // 10**10


def test_compute_alerts_accumulates_below_threshold():
    # baseline = last-alerted level, so small stakes pile up until the line
    threshold = 80 * sa._RAO
    alerts, base = sa.compute_alerts({"alpha:ab:0": 25 * sa._RAO}, {}, threshold)
    assert alerts == [] and base.get("alpha:ab:0", 0) == 0
    alerts, base = sa.compute_alerts({"alpha:ab:0": 50 * sa._RAO}, base, threshold)
    assert alerts == [] and base.get("alpha:ab:0", 0) == 0
    # 4x25 crosses the line — one alert for the accumulated 100
    alerts, base = sa.compute_alerts({"alpha:ab:0": 100 * sa._RAO}, base, threshold)
    assert len(alerts) == 1
    assert alerts[0]["delta_rao"] == 100 * sa._RAO
    assert base["alpha:ab:0"] == 100 * sa._RAO
    # post-alert small top-up stays quiet
    alerts, base = sa.compute_alerts({"alpha:ab:0": 125 * sa._RAO}, base, threshold)
    assert alerts == [] and base["alpha:ab:0"] == 100 * sa._RAO


def test_compute_alerts_decrease_resets_baseline():
    threshold = 80 * sa._RAO
    base = {"alpha:ab:0": 100 * sa._RAO}
    alerts, base = sa.compute_alerts({"alpha:ab:0": 20 * sa._RAO}, base, threshold)
    assert alerts == [] and base["alpha:ab:0"] == 20 * sa._RAO
    # re-stake must re-accumulate from the reset baseline
    alerts, base = sa.compute_alerts({"alpha:ab:0": 95 * sa._RAO}, base, threshold)
    assert alerts == [] and base.get("alpha:ab:0", 0) == 20 * sa._RAO
    alerts, base = sa.compute_alerts({"alpha:ab:0": 101 * sa._RAO}, base, threshold)
    assert len(alerts) == 1 and alerts[0]["delta_rao"] == 81 * sa._RAO


def test_compute_alerts_vanished_entry_resets_to_zero():
    base = {"alpha:ab:0": 100 * sa._RAO}
    alerts, base = sa.compute_alerts({}, base, 80 * sa._RAO)
    assert alerts == [] and base["alpha:ab:0"] == 0


def test_format_single_alert():
    ck = "ab" * 32
    alert = {"key": f"alpha:{ck}:0", "delta_rao": int(95.2 * sa._RAO), "total_rao": 0}
    msg = sa.format_stake_message([alert], 4_521_003)
    assert "New stake to Subnet Summer validator" in msg
    assert "95.2τ" in msg
    assert "head 4521003" in msg
    assert ck not in msg  # short form only


def test_format_digest_when_many_alerts():
    alerts = [
        {"key": f"alpha:{'ab' * 32}:{i}", "delta_rao": int(90 * sa._RAO), "total_rao": 0}
        for i in range(4)
    ]
    msg = sa.format_stake_message(alerts, None)
    assert "4 new stakes" in msg
    assert "360.0τ combined" in msg
    assert "head" not in msg


def test_format_digest_for_two_alerts():
    alerts = [
        {"key": f"alpha:{'ab' * 32}:0", "delta_rao": int(90 * sa._RAO), "total_rao": 0},
        {"key": f"alpha:{'cd' * 32}:1", "delta_rao": int(85 * sa._RAO), "total_rao": 0},
    ]
    msg = sa.format_stake_message(alerts, None)
    assert "2 new stakes" in msg and "175.0τ combined" in msg


class _FakeClient:
    """Serves fabricated Alpha keys/values without touching the network."""

    def __init__(self, keys_with_values):
        self.kv = keys_with_values

    def _call_quiet(self, method, params):
        if method == "state_getKeysPaged":
            prefix = params[0]
            return [k for k in self.kv if k.startswith(prefix)]
        if method == "state_getStorageAt":
            return self.kv.get(params[0])
        return None

    def is_healthy(self):
        return True

    def get_current_block(self):
        return 123


def test_scan_hotkey_stakes_reads_both_maps():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    ck = bytes(range(32))
    u64f64 = "0x" + ((5 * sa._RAO) << 64).to_bytes(16, "little").hex()
    safe_float = "0x" + ((5 * sa._RAO * 10**11).to_bytes(16, "little") + (-11).to_bytes(8, "little", signed=True)).hex()
    keys = {}
    for map_name, val in (("Alpha", u64f64), ("AlphaV2", safe_float)):
        full = (
            sa.alpha_storage_prefix(map_name, pub)
            + sa._blake2_concat(ck)
            + (3).to_bytes(2, "little")
        )
        keys["0x" + full.hex()] = val
    client = _FakeClient(keys)
    out = sa.scan_hotkey_stakes(client, pub)
    assert out == {
        f"Alpha:{ck.hex()}:3": 5 * sa._RAO,
        f"AlphaV2:{ck.hex()}:3": 5 * sa._RAO,
    }
