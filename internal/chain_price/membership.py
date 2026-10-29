"""NetworksAdded membership helpers (#1395 Step 2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.storage_keys import (
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
    total_networks_key_hex,
)

from internal.chain_read import ChainRead
from internal.chain_rpc_errors import storage_block_matches


def decode_total_networks(raw: Any) -> Optional[int]:
    """SubtensorModule.TotalNetworks: exactly 2 bytes, u16 little-endian."""
    if not isinstance(raw, str) or not raw.startswith("0x"):
        return None
    hex_body = raw[2:]
    if len(hex_body) != 4:
        return None
    try:
        data = bytes.fromhex(hex_body)
    except ValueError:
        return None
    if len(data) != 2:
        return None
    value = int.from_bytes(data, "little")
    return value if value > 0 else None


def decode_networks_added_bool(raw: Any) -> Optional[bool]:
    """SCALE bool: 0x00 = false, 0x01 = true. None when the value is absent or not a bool."""
    if not isinstance(raw, str):
        return None
    text = raw.lower()
    if text == "0x00":
        return False
    if text == "0x01":
        return True
    return None


def get_member_netuids(
    call: Callable[[str, list], Tuple[Optional[Any], RpcOutcome]],
    at_hash: str,
) -> Tuple[List[int], RpcOutcome]:
    """Return netuids with NetworksAdded == true at ``at_hash`` (excludes netuid 0)."""
    prefix = networks_added_prefix_hex()
    keys: List[str] = []
    start: Optional[str] = None
    while True:
        params = [prefix, 200, start, at_hash]
        page, outcome = call("state_getKeysPaged", params)
        if outcome != "ok":
            return [], outcome
        if not page:
            break
        keys.extend(page)
        if len(page) < 200:
            break
        start = page[-1]
    if not keys:
        return [], "absent"

    total_key = total_networks_key_hex()
    query_keys = list(keys) + [total_key]
    batch, outcome = call("state_queryStorageAt", [query_keys, at_hash])
    if outcome != "ok":
        return [], outcome
    if not batch or not storage_block_matches(batch[0], at_hash):
        return [], "invalid"
    changes = batch[0].get("changes") if isinstance(batch[0], dict) else None
    if not isinstance(changes, list) or not changes:
        return [], "invalid"
    expected = {key.lower() for key in query_keys}
    by_key: Dict[str, Any] = {}
    for row in changes:
        if not isinstance(row, (list, tuple)) or len(row) != 2 or not isinstance(row[0], str):
            return [], "invalid"
        key = row[0].lower()
        if key in by_key or key not in expected:
            return [], "invalid"
        by_key[key] = row[1]

    total_networks = decode_total_networks(by_key.get(total_key.lower()))
    if total_networks is None:
        return [], "invalid"

    netuids: List[int] = []
    for key in keys:
        flag = decode_networks_added_bool(by_key.get(key.lower()))
        if flag is None:
            return [], "invalid"
        netuid = netuid_from_networks_added_key(key)
        if flag and netuid != 0:
            netuids.append(netuid)

    member_count_incl_root = len(netuids) + 1
    if total_networks != member_count_incl_root:
        return [], "invalid"
    return sorted(set(netuids)), "ok"


def read_chain_membership(reader: Any) -> Tuple[Optional[ChainRead], RpcOutcome]:
    # A real ChainReader refuses a head that is not a full 64-hex hash; a bare reader double that only
    # has ``pin_finalized_head`` is read as before (the universe layer tolerates unpinned reads, but
    # admission, completeness and reload never accept them).
    pin = getattr(reader, "pin_finalized_head_strict", None) or reader.pin_finalized_head
    at_hash, outcome = pin()
    if outcome != "ok" or not at_hash:
        return None, outcome if outcome != "ok" else "absent"
    members, outcome = get_member_netuids(reader.call_fn(), at_hash)
    if outcome != "ok":
        return None, outcome
    chain = ChainRead.parse(
        {
            "block_hash": str(at_hash).lower(),
            "netuids": members,
            "rpc": getattr(reader, "provider_served", None),
        },
        pinned=False,
    )
    if chain is None:
        return None, "invalid"
    return chain, "ok"
