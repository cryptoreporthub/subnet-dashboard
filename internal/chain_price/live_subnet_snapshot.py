"""Batched live subnet price snapshot (NetworksAdded membership + storage reserves)."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from internal.chain_client import _hex_to_bytes, _row_from_subnet_reserves, _storage_chunk_netuids
from internal.chain_price import config as chain_price_cfg
from internal.chain_price.membership import get_member_netuids
from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.reader import ChainReader
from internal.chain_price.storage_keys import map_key_hex

logger = logging.getLogger(__name__)

_STORAGE_CHUNK_NETUIDS = 128

NetuidOutcome = str


@dataclass
class LiveSubnetSnapshot:
    block_hash: str
    provider: str
    rows: List[dict]
    netuid_outcomes: Dict[int, NetuidOutcome] = field(default_factory=dict)
    batch_expired: bool = False
    requested_netuids: List[int] = field(default_factory=list)
    membership_resolved: bool = False
    failure: Optional[str] = None


def _remaining_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _outcome_label(outcome: RpcOutcome) -> NetuidOutcome:
    if outcome == "ok":
        return "ok"
    if outcome in (
        "absent",
        "invalid",
        "archive_miss",
        "rate_limited",
        "rpc_error",
        "timeout",
        "connection",
        "parse",
    ):
        return outcome
    return "rpc_error"


def _fail_all(requested: List[int], label: NetuidOutcome) -> Dict[int, NetuidOutcome]:
    return {int(n): label for n in requested}


def _strict_decode_u64(raw: Any) -> Tuple[Optional[int], Optional[NetuidOutcome]]:
    if raw is None or raw == "0x" or raw == "0x00":
        return None, None
    try:
        raw_bytes = _hex_to_bytes(raw)
    except (TypeError, ValueError):
        return None, "parse"
    if len(raw_bytes) != 8:
        return None, "parse"
    return int.from_bytes(raw_bytes, "little"), None


def _parse_subnet_reserve_changes(
    changes: Any,
    chunk: List[int],
) -> Tuple[Dict[int, Tuple[int, int]], Dict[int, NetuidOutcome]]:
    """Map SubnetTAO/SubnetAlphaIn for one storage chunk; reject malformed RPC rows."""
    allowed: set[str] = set()
    keys_for_netuid: Dict[int, Tuple[str, str]] = {}
    for netuid in chunk:
        tao_key = map_key_hex(b"SubnetTAO", netuid)
        alpha_key = map_key_hex(b"SubnetAlphaIn", netuid)
        allowed.add(tao_key)
        allowed.add(alpha_key)
        keys_for_netuid[netuid] = (tao_key, alpha_key)

    if not isinstance(changes, list):
        return {}, {int(n): "invalid" for n in chunk}

    by_key: Dict[str, Any] = {}
    for row in changes:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            return {}, {int(n): "parse" for n in chunk}
        key, value = row[0], row[1]
        if key not in allowed:
            return {}, {int(n): "invalid" for n in chunk}
        if key in by_key:
            return {}, {int(n): "invalid" for n in chunk}
        by_key[key] = value

    reserves: Dict[int, Tuple[int, int]] = {}
    outcomes: Dict[int, NetuidOutcome] = {}
    for netuid in chunk:
        tao_key, alpha_key = keys_for_netuid[netuid]
        tao_raw, tao_err = _strict_decode_u64(by_key.get(tao_key))
        if tao_err:
            outcomes[netuid] = tao_err
            continue
        alpha_raw, alpha_err = _strict_decode_u64(by_key.get(alpha_key))
        if alpha_err:
            outcomes[netuid] = alpha_err
            continue
        if tao_raw is None or alpha_raw is None or alpha_raw == 0:
            outcomes[netuid] = "no_price"
            continue
        reserves[netuid] = (tao_raw, alpha_raw)
    return reserves, outcomes


def _failed_snapshot(
    *,
    block_hash: str = "",
    provider: str = "",
    failure: str,
    batch_expired: bool = False,
    requested: Optional[List[int]] = None,
    outcomes: Optional[Dict[int, NetuidOutcome]] = None,
) -> LiveSubnetSnapshot:
    return LiveSubnetSnapshot(
        block_hash=block_hash,
        provider=provider,
        rows=[],
        netuid_outcomes=dict(outcomes or {}),
        batch_expired=batch_expired,
        requested_netuids=list(requested or []),
        membership_resolved=False,
        failure=failure,
    )


@contextmanager
def _clamp_reader_timeouts(reader: ChainReader, seconds: float):
    """Temporarily cap per-provider HTTP timeouts to the remaining budget."""
    if seconds <= 0:
        seconds = 0.01
    originals: List[Tuple[Any, float]] = []
    for _label, client in reader._providers:
        originals.append((client, float(client.timeout)))
        client.timeout = min(float(client.timeout), seconds)
    try:
        yield
    finally:
        for client, original in originals:
            client.timeout = original


def fetch_live_subnet_snapshot(deadline: float) -> LiveSubnetSnapshot:
    """Pin finalized head, read active members, batch-fetch SubnetTAO/SubnetAlphaIn reserves."""
    if time.monotonic() >= deadline:
        return _failed_snapshot(failure="snapshot:deadline", batch_expired=True)

    reader = ChainReader(chain_price_cfg.rpc_provider_clients())
    reader.rpc_deadline_mono = deadline
    with _clamp_reader_timeouts(reader, _remaining_seconds(deadline)):
        call = reader.call_fn()

        if time.monotonic() >= deadline:
            return _failed_snapshot(failure="snapshot:deadline", batch_expired=True)

        block_hash, pin_outcome = reader.pin_finalized_head()
        if pin_outcome != "ok" or not block_hash:
            label = _outcome_label(pin_outcome if pin_outcome != "ok" else "rpc_error")
            return _failed_snapshot(
                provider=reader.provider_served or "",
                failure=f"head_pin:{label}",
            )

        if time.monotonic() >= deadline:
            return _failed_snapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                failure="membership:deadline",
                batch_expired=True,
            )

        members, mem_outcome = get_member_netuids(call, block_hash)
        if mem_outcome != "ok":
            label = _outcome_label(mem_outcome)
            return _failed_snapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                failure=f"membership:{label}",
            )

        requested = sorted({int(n) for n in members})
        outcomes: Dict[int, NetuidOutcome] = {}

        if time.monotonic() >= deadline:
            return _failed_snapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                failure="membership:deadline",
                batch_expired=True,
                requested=requested,
                outcomes=_fail_all(requested, "batch_expired"),
            )

        chunk_size = _STORAGE_CHUNK_NETUIDS

        rows: List[dict] = []
        last_price_provider = reader.provider_served or chain_price_cfg.primary_rpc_endpoint()[1]

        for chunk in _storage_chunk_netuids(requested, chunk_size):
            if time.monotonic() >= deadline:
                for n in chunk:
                    outcomes[n] = "batch_expired"
                for n in requested:
                    outcomes.setdefault(n, "batch_expired")
                break

            keys: List[str] = []
            for netuid in chunk:
                keys.append(map_key_hex(b"SubnetTAO", netuid))
                keys.append(map_key_hex(b"SubnetAlphaIn", netuid))

            batch, storage_outcome = call("state_queryStorageAt", [keys, block_hash])
            if storage_outcome != "ok" or not batch:
                label = _outcome_label(storage_outcome)
                for n in chunk:
                    outcomes[n] = label
                continue

            if time.monotonic() >= deadline:
                for n in chunk:
                    outcomes[n] = "batch_expired"
                continue

            chunk_provider = reader.provider_served or last_price_provider
            last_price_provider = chunk_provider

            entry = batch[0] if isinstance(batch[0], dict) else {}
            reserves, chunk_outcomes = _parse_subnet_reserve_changes(entry.get("changes"), chunk)
            for netuid, label in chunk_outcomes.items():
                outcomes[netuid] = label
            for netuid, (tao_raw, alpha_raw) in reserves.items():
                rows.append(_row_from_subnet_reserves(netuid, tao_raw, alpha_raw, chunk_provider))
                outcomes[netuid] = "ok"

        for n in requested:
            outcomes.setdefault(n, "batch_expired")

        batch_expired = any(outcomes.get(n) == "batch_expired" for n in requested)
        rows.sort(key=lambda r: r["netuid"])
        logger.info(
            "live_subnet_snapshot: %d rows provider=%s members=%d batch_expired=%s",
            len(rows),
            last_price_provider,
            len(requested),
            batch_expired,
        )
        return LiveSubnetSnapshot(
            block_hash=block_hash,
            provider=last_price_provider,
            rows=rows,
            netuid_outcomes=dict(outcomes),
            batch_expired=batch_expired,
            requested_netuids=requested,
            membership_resolved=True,
            failure=None,
        )
