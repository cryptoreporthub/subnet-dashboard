"""NetworksAdded membership helpers (#1395 Step 2)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.storage_keys import (
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
)

from internal.chain_client import _hex_to_bytes


def decode_networks_added_bool(raw: Any) -> bool:
    if raw is None or raw == "0x" or raw == "0x00":
        return False
    try:
        data = _hex_to_bytes(raw)
    except (TypeError, ValueError):
        return False
    if not data:
        return False
    # SCALE bool: 0x00 = false, 0x01 = true
    return data[0] != 0


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
    if outcome != "ok" or not batch:
        return [], outcome
    changes = batch[0].get("changes") if isinstance(batch[0], dict) else None
    if not changes:
        return [], "absent"
    by_key: Dict[str, Any] = {row[0]: row[1] for row in changes if row}
    netuids: List[int] = []
    for key in keys:
        netuid = netuid_from_networks_added_key(key)
        if netuid == 0:
            continue
        if decode_networks_added_bool(by_key.get(key)):
            netuids.append(netuid)
    return sorted(set(netuids)), "ok"
