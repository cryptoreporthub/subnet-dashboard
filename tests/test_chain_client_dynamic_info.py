from internal.chain_client import _decode_dynamic_info_pool


def _compact(value: int) -> bytes:
    if value < 1 << 6:
        return bytes([value << 2])
    if value < 1 << 14:
        encoded = value << 2 | 1
        return encoded.to_bytes(2, "little")
    if value < 1 << 30:
        encoded = value << 2 | 2
        return encoded.to_bytes(4, "little")
    raw = value.to_bytes((value.bit_length() + 7) // 8, "little")
    return bytes([(len(raw) - 4) << 2 | 3]) + raw


def _dynamic_info_fixture():
    # Option::Some + netuid + hotkey + coldkey + name + symbol +
    # tempo/last-step/blocks/emission + alpha_in + alpha_out + tao_in.
    fields = [
        _compact(1),
        bytes(32),
        bytes(32),
        _compact(3) + b"".join(_compact(ord(char)) for char in "Foo"),
        _compact(1) + _compact(ord("F")),
        _compact(99),
        _compact(100),
        _compact(2),
        _compact(0),
        _compact(3_000_000_000),
        _compact(2_000_000_000),
        _compact(15_000_000_000),
    ]
    return bytes([1]) + b"".join(fields)


def test_dynamic_info_decodes_tao_and_alpha_reserves():
    pool = _decode_dynamic_info_pool(_dynamic_info_fixture())

    assert pool["netuid"] == 1
    assert pool["name"] == "Foo"
    assert pool["total_alpha"] == 3.0
    assert pool["total_tao"] == 15.0
    assert pool["tao_reserve_raw"] == 15_000_000_000
    assert pool["liquidity"] == 30.0


def test_dynamic_info_empty_option_is_honest():
    assert _decode_dynamic_info_pool([0]) is None