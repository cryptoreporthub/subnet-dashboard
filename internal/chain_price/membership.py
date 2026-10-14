"""NetworksAdded membership helpers (#1395 Step 2)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.storage_keys import (
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
)

from internal.chain_client import _hex_to_bytes
from internal.chain_rpc_errors import storage_block_matches


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

    batch, outcome = call("state_queryStorageAt", [keys, at_hash])
    if outcome != "ok":
        return [], outcome
    # Fail closed: the netuid list is derived from this response, so it must echo at_hash.
    if not batch or not storage_block_matches(batch[0], at_hash):
        return [], "invalid"
    changes = batch[0].get("changes") if isinstance(batch[0], dict) else None
    if not changes:
        # Keys were enumerated at at_hash, so an empty value set is a malformed response, not absence.
        return [], "invalid"
    by_key: Dict[str, Any] = {str(row[0]).lower(): row[1] for row in changes if row}
    netuids: List[int] = []
    for key in keys:
        # Every enumerated key needs a decodable bool; a missing or malformed value is never "false".
        flag = decode_networks_added_bool(by_key.get(key.lower()))
        if flag is None:
            return [], "invalid"
        netuid = netuid_from_networks_added_key(key)
        if flag and netuid != 0:
            netuids.append(netuid)
    return sorted(set(netuids)), "ok"
