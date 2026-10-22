"""NetworksAdded membership helpers (#1395 Step 2)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_price.outcomes import RpcOutcome
from internal.chain_client import _decode_scale_compact, _hex_to_bytes
from internal.chain_price.storage_keys import (
    netuid_from_networks_added_key,
    networks_added_prefix_hex,
    total_networks_key_hex,
)

from internal.chain_rpc_errors import storage_block_matches


def decode_total_networks(raw: Any) -> Optional[int]:
    """SCALE compact count from SubtensorModule.TotalNetworks."""
    if not isinstance(raw, str) or not raw.startswith("0x"):
        return None
    try:
        data = _hex_to_bytes(raw)
    except Exception:
        return None
    if not data:
        return None
    # On Finney/Blockmachine, TotalNetworks is stored as u16 LE (129 -> 0x8100).
    if len(data) == 2:
        value = int.from_bytes(data, "little")
        return value if value > 0 else None
    value, _consumed = _decode_scale_compact(data)
    if value < 0:
        return None
    return int(value)


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
    # Keys were enumerated at at_hash, so an empty value set is a malformed response, not absence.
    if not isinstance(changes, list) or not changes:
        return [], "invalid"
    expected = {key.lower() for key in keys}
    by_key: Dict[str, Any] = {}
    for row in changes:
        if not isinstance(row, (list, tuple)) or len(row) != 2 or not isinstance(row[0], str):
            return [], "invalid"
        key = row[0].lower()
        # A duplicate or unrequested key means the response is not a one-to-one answer to the enumeration.
        if key in by_key or key not in expected:
            return [], "invalid"
        by_key[key] = row[1]
    netuids: List[int] = []
    for key in keys:
        # Every enumerated key needs a decodable bool; a missing or malformed value is never "false".
        flag = decode_networks_added_bool(by_key.get(key.lower()))
        if flag is None:
            return [], "invalid"
        netuid = netuid_from_networks_added_key(key)
        if flag and netuid != 0:
            netuids.append(netuid)
    member_count_incl_root = len(netuids) + 1
    total_key = total_networks_key_hex()
    total_batch, outcome = call("state_queryStorageAt", [[total_key], at_hash])
    if outcome != "ok":
        return [], outcome
    if not total_batch or not storage_block_matches(total_batch[0], at_hash):
        return [], "invalid"
    total_changes = total_batch[0].get("changes") if isinstance(total_batch[0], dict) else None
    if not isinstance(total_changes, list) or len(total_changes) != 1:
        return [], "invalid"
    row = total_changes[0]
    if not isinstance(row, (list, tuple)) or len(row) != 2:
        return [], "invalid"
    total_networks = decode_total_networks(row[1])
    if total_networks is None or total_networks != member_count_incl_root:
        return [], "invalid"
    return sorted(set(netuids)), "ok"
