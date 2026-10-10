"""Stake-alert logic: Substrate primitives, diff/accumulate, formatting."""

from __future__ import annotations

import json

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

    def _call(self, method, params):
        return self._call_quiet(method, params)

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


class _FailingPagedClient(_FakeClient):
    def __init__(self, keys_with_values, fail_at_page: int = 0):
        super().__init__(keys_with_values)
        self.fail_at_page = fail_at_page
        self._page_calls = 0

    def _call(self, method, params):
        if method == "state_getKeysPaged":
            if self._page_calls == self.fail_at_page:
                raise RuntimeError("RPC down")
            self._page_calls += 1
        return super()._call(method, params)


class _FailingStorageClient(_FakeClient):
    def __init__(self, keys_with_values, fail_key: str):
        super().__init__(keys_with_values)
        self.fail_key = fail_key

    def _call(self, method, params):
        if method == "state_getStorageAt" and params[0] == self.fail_key:
            raise RuntimeError("storage read failed")
        return super()._call(method, params)


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


def test_scan_hotkey_stakes_aborts_on_first_page_rpc_failure():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    client = _FailingPagedClient({}, fail_at_page=0)
    with pytest.raises(sa.StakeScanIncomplete):
        sa.scan_hotkey_stakes(client, pub)


def test_scan_hotkey_stakes_aborts_on_later_page_rpc_failure():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    ck = bytes(range(32))
    u64f64 = "0x" + ((5 * sa._RAO) << 64).to_bytes(16, "little").hex()
    keys = {}
    for i in range(201):
        full = (
            sa.alpha_storage_prefix("Alpha", pub)
            + sa._blake2_concat(ck)
            + i.to_bytes(2, "little")
        )
        keys["0x" + full.hex()] = u64f64
    client = _FailingPagedClient(keys, fail_at_page=1)
    with pytest.raises(sa.StakeScanIncomplete):
        sa.scan_hotkey_stakes(client, pub)


def test_scan_hotkey_stakes_aborts_on_storage_value_failure():
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    ck = bytes(range(32))
    u64f64 = "0x" + ((5 * sa._RAO) << 64).to_bytes(16, "little").hex()
    full = (
        sa.alpha_storage_prefix("Alpha", pub)
        + sa._blake2_concat(ck)
        + (3).to_bytes(2, "little")
    )
    key = "0x" + full.hex()
    client = _FailingStorageClient({key: u64f64}, fail_key=key)
    with pytest.raises(sa.StakeScanIncomplete):
        sa.scan_hotkey_stakes(client, pub)


def test_check_stake_alerts_incomplete_scan_preserves_baseline(tmp_path, monkeypatch):
    state_file = tmp_path / "stake_alert_state.json"
    monkeypatch.setattr(sa, "STATE_PATH", str(state_file))
    baseline = {"alpha:ab:0": 100 * sa._RAO}
    state_file.write_text(
        json.dumps({"initialized": True, "baseline": baseline, "hotkey": sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY).hex()}),
        encoding="utf-8",
    )
    client = _FailingPagedClient({}, fail_at_page=0)
    assert sa.check_stake_alerts(client=client) is None
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["baseline"] == baseline


def test_check_stake_alerts_recovery_after_rpc_blip_no_false_alert(tmp_path, monkeypatch):
    state_file = tmp_path / "stake_alert_state.json"
    monkeypatch.setattr(sa, "STATE_PATH", str(state_file))
    pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    ck = bytes(range(32))
    u64f64 = "0x" + ((100 * sa._RAO) << 64).to_bytes(16, "little").hex()
    full = (
        sa.alpha_storage_prefix("Alpha", pub)
        + sa._blake2_concat(ck)
        + (0).to_bytes(2, "little")
    )
    key = "0x" + full.hex()
    stake_key = f"Alpha:{ck.hex()}:0"
    state_file.write_text(
        json.dumps({"initialized": True, "baseline": {stake_key: 100 * sa._RAO}, "hotkey": pub.hex()}),
        encoding="utf-8",
    )
    failing = _FailingPagedClient({key: u64f64}, fail_at_page=0)
    assert sa.check_stake_alerts(client=failing) is None
    ok = _FakeClient({key: u64f64})
    monkeypatch.setattr(sa, "alert_chat_id", lambda: None)
    result = sa.check_stake_alerts(client=ok)
    assert result is None
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["baseline"][stake_key] == 100 * sa._RAO


def test_compute_alerts_skips_missing_price_preserves_baseline():
    threshold = 80 * sa._RAO
    share_delta = 100 * sa._RAO  # would be 100τ at bogus 1:1
    key = "alpha:ab:0"
    base = {key: 0}
    alerts, new_base = sa.compute_alerts(
        {key: share_delta},
        base,
        threshold,
        price_lookup=lambda _netuid: None,
    )
    assert alerts == []
    assert new_base[key] == 0


def test_compute_alerts_price_boundary_below_threshold():
    threshold = 80 * sa._RAO
    key = "alpha:ab:7"
    # 0.1 τ/α × 790α = 79τ (below line)
    alerts, base = sa.compute_alerts(
        {key: 790 * sa._RAO},
        {key: 0},
        threshold,
        price_lookup=lambda _netuid: 0.1,
    )
    assert alerts == []
    assert base[key] == 0


def test_compute_alerts_price_boundary_at_threshold():
    threshold = 80 * sa._RAO
    key = "alpha:ab:7"
    alerts, base = sa.compute_alerts(
        {key: 800 * sa._RAO},
        {key: 0},
        threshold,
        price_lookup=lambda _netuid: 0.1,
    )
    assert len(alerts) == 1
    assert alerts[0]["delta_rao"] == 80 * sa._RAO
    assert base[key] == 800 * sa._RAO


def test_compute_alerts_retries_after_price_becomes_available():
    threshold = 80 * sa._RAO
    key = "alpha:ab:7"
    base = {key: 0}
    prices = {7: None}

    def lookup(netuid):
        return prices[netuid]

    alerts, base = sa.compute_alerts({key: 800 * sa._RAO}, base, threshold, price_lookup=lookup)
    assert alerts == [] and base[key] == 0
    prices[7] = 0.1
    alerts, base = sa.compute_alerts({key: 800 * sa._RAO}, base, threshold, price_lookup=lookup)
    assert len(alerts) == 1


def test_check_stake_alerts_hotkey_change_reinits_without_alert(tmp_path, monkeypatch):
    state_file = tmp_path / "stake_alert_state.json"
    monkeypatch.setattr(sa, "STATE_PATH", str(state_file))
    old_pub = sa.ss58_to_pubkey(sa.DEFAULT_HOTKEY)
    new_hotkey = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
    new_pub = sa.ss58_to_pubkey(new_hotkey)
    ck = bytes(range(32))
    u64f64 = "0x" + ((200 * sa._RAO) << 64).to_bytes(16, "little").hex()
    full = (
        sa.alpha_storage_prefix("Alpha", new_pub)
        + sa._blake2_concat(ck)
        + (1).to_bytes(2, "little")
    )
    key = "0x" + full.hex()
    stake_key = f"Alpha:{ck.hex()}:1"
    state_file.write_text(
        json.dumps(
            {
                "initialized": True,
                "baseline": {stake_key: 50 * sa._RAO},
                "hotkey": old_pub.hex(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STAKE_ALERT_HOTKEY", new_hotkey)
    client = _FakeClient({key: u64f64})
    result = sa.check_stake_alerts(client=client)
    assert result == {"baseline": True, "entries": 1}
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["hotkey"] == new_pub.hex()
    assert saved["baseline"][stake_key] == 200 * sa._RAO
