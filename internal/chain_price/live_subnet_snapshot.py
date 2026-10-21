"""Batched live subnet price snapshot (NetworksAdded membership + storage reserves)."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from internal.chain_client import _decode_storage_u64, _row_from_subnet_reserves, _storage_chunk_netuids
from internal.chain_price import config as chain_price_cfg
from internal.chain_price.membership import get_member_netuids
from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.reader import ChainReader
from internal.chain_price.storage_keys import map_key_hex

logger = logging.getLogger(__name__)

NetuidOutcome = str


@dataclass
class LiveSubnetSnapshot:
    block_hash: str
    provider: str
    rows: List[dict]
    netuid_outcomes: Dict[int, NetuidOutcome] = field(default_factory=dict)
    batch_expired: bool = False
    requested_netuids: List[int] = field(default_factory=list)


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


@contextmanager
def _clamp_reader_timeouts(reader: ChainReader, seconds: float):
    """Temporarily cap per-provider HTTP timeouts to the remaining batch budget."""
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
    empty = LiveSubnetSnapshot(block_hash="", provider="", rows=[], requested_netuids=[])

    if time.monotonic() >= deadline:
        return empty

    reader = ChainReader(chain_price_cfg.rpc_provider_clients())
    with _clamp_reader_timeouts(reader, _remaining_seconds(deadline)):
        call = reader.call_fn()

        if time.monotonic() >= deadline:
            return empty

        block_hash, pin_outcome = reader.pin_finalized_head()
        if pin_outcome != "ok" or not block_hash:
            label = _outcome_label(pin_outcome if pin_outcome != "ok" else "rpc_error")
            return LiveSubnetSnapshot(
                block_hash="",
                provider=reader.provider_served or "",
                rows=[],
                netuid_outcomes={},
                batch_expired=False,
                requested_netuids=[],
            )

        if time.monotonic() >= deadline:
            return LiveSubnetSnapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                rows=[],
                netuid_outcomes={},
                batch_expired=True,
                requested_netuids=[],
            )

        members, mem_outcome = get_member_netuids(call, block_hash)
        requested = sorted({int(n) for n in members})
        outcomes: Dict[int, NetuidOutcome] = {}

        if mem_outcome != "ok":
            label = _outcome_label(mem_outcome)
            return LiveSubnetSnapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                rows=[],
                netuid_outcomes=_fail_all(requested, label) if requested else {},
                batch_expired=False,
                requested_netuids=requested,
            )

        if time.monotonic() >= deadline:
            outcomes = _fail_all(requested, "batch_expired")
            return LiveSubnetSnapshot(
                block_hash=block_hash,
                provider=reader.provider_served or "",
                rows=[],
                netuid_outcomes=outcomes,
                batch_expired=True,
                requested_netuids=requested,
            )

        try:
            chunk_size = int(os.environ.get("LIVE_SUBNETS_STORAGE_CHUNK_NETUIDS", "128"))
        except ValueError:
            chunk_size = 128

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

            chunk_provider = reader.provider_served or last_price_provider
            last_price_provider = chunk_provider

            entry = batch[0] if isinstance(batch[0], dict) else {}
            changes = entry.get("changes")
            if not isinstance(changes, list):
                for n in chunk:
                    outcomes[n] = "no_price"
                continue
            by_key = {row[0]: row[1] for row in changes if row}
            for netuid in chunk:
                tao_raw = _decode_storage_u64(by_key.get(map_key_hex(b"SubnetTAO", netuid)))
                alpha_raw = _decode_storage_u64(by_key.get(map_key_hex(b"SubnetAlphaIn", netuid)))
                if tao_raw is None or alpha_raw is None or alpha_raw == 0:
                    outcomes[netuid] = "no_price"
                    continue
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
        )


def snapshot_batch_result(
    snapshot: LiveSubnetSnapshot,
    *,
    universe_netuids: Optional[List[int]] = None,
) -> dict:
    """Compat dict for chain_client / legacy callers; marks non-members outside the active set."""
    outcomes = dict(snapshot.netuid_outcomes)
    requested = list(snapshot.requested_netuids)
    if universe_netuids:
        member_set = set(requested)
        for n in sorted({int(x) for x in universe_netuids}):
            if n not in member_set:
                outcomes[n] = "not_member"
    return {
        "rows": list(snapshot.rows),
        "batch_expired": snapshot.batch_expired,
        "netuid_outcomes": outcomes,
        "block_hash": snapshot.block_hash,
        "provider": snapshot.provider,
        "requested_netuids": requested,
    }
