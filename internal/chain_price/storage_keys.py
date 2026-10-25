"""Subtensor storage key helpers for chain price sampling."""

from __future__ import annotations

import struct
from typing import Iterable, List

from internal.message_intel.stake_alert import twox128

_SUBTENSOR = twox128(b"SubtensorModule")
_NETWORKS_ADDED = _SUBTENSOR + twox128(b"NetworksAdded")
_TOTAL_NETWORKS = _SUBTENSOR + twox128(b"TotalNetworks")
_TIMESTAMP_NOW = twox128(b"Timestamp") + twox128(b"Now")


def networks_added_prefix_hex() -> str:
    return "0x" + _NETWORKS_ADDED.hex()


def total_networks_key_hex() -> str:
    return "0x" + _TOTAL_NETWORKS.hex()


def timestamp_now_key_hex() -> str:
    return "0x" + _TIMESTAMP_NOW.hex()


def map_key_hex(map_name: bytes, netuid: int) -> str:
    return "0x" + (_SUBTENSOR + twox128(map_name) + struct.pack("<H", netuid)).hex()


def netuid_from_networks_added_key(key_hex: str) -> int:
    """Decode netuid from a NetworksAdded storage key (prefix + u16 LE)."""
    body = bytes.fromhex(key_hex[2:] if key_hex.startswith("0x") else key_hex)
    return int.from_bytes(body[-2:], "little")


def reserve_query_keys(netuids: Iterable[int]) -> List[str]:
    keys: List[str] = []
    for netuid in netuids:
        for map_name in (b"SubnetTAO", b"SubnetAlphaIn", b"NetworkRegisteredAt"):
            keys.append(map_key_hex(map_name, netuid))
    keys.append(timestamp_now_key_hex())
    return keys
