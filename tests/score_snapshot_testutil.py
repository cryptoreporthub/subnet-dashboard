"""Helpers for complete score-snapshot fixtures (PR-B)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.chain_read import ChainRead
from internal.council.scorer_identity import (
    compute_input_digest,
    current_scorer_digest,
    current_weights_digest,
    stamp_scorer_fields,
)
from internal.council.snapshot_coverage import membership_generation

PINNED_HASH = "0x" + "ef" * 32


def chain_read(netuids: Any) -> ChainRead:
    return ChainRead(PINNED_HASH, tuple(sorted(int(n) for n in netuids)), "finney")


def chain_dict(netuids: Any) -> Dict[str, Any]:
    return chain_read(netuids).to_dict()


def receipt_provenance(netuids: Any) -> Dict[str, Any]:
    """The chain-provenance fields a real membership receipt carries."""
    chain = chain_read(netuids)
    return {
        "expected_netuids": list(chain.netuids),
        "generation": membership_generation(chain.netuids),
        "block_hash": chain.block_hash,
        "rpc": chain.rpc,
        "chain": chain.to_dict(),
        "fresh": True,
    }


def snapshot_provenance(
    netuids: Any,
    *,
    resolved_at: str = "2026-10-17T00:00:00Z",
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Provenance with the live digests, so a fixture is fresh exactly when a real build would be."""
    chain = chain_read(netuids)
    generation = membership_generation(chain.netuids)
    scored_rows = rows if rows is not None else [{"netuid": int(n)} for n in chain.netuids]
    return {
        "membership_generation": generation,
        "membership_block_hash": chain.block_hash,
        "membership_rpc": chain.rpc,
        "membership_resolved_at": resolved_at,
        "weights_digest": current_weights_digest(),
        "input_digest": compute_input_digest(generation, current_scorer_digest(), scored_rows, {}),
    }


def complete_snapshot_rows(
    netuids: Optional[List[int]] = None,
    *,
    score: float = 90.0,
) -> List[Dict[str, Any]]:
    ids = netuids or [2, 3]
    return [{"netuid": n, "total_score": score, "name": f"S{n}"} for n in ids]


def complete_snapshot_payload(
    day_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    hour_rows: Optional[List[Dict[str, Any]]] = None,
    written_at: str = "2026-10-17T00:00:00Z",
) -> Dict[str, Any]:
    day = day_rows or complete_snapshot_rows()
    hour = hour_rows if hour_rows is not None else list(day)
    expected = [int(r["netuid"]) for r in day]
    return stamp_scorer_fields(
        {
            "written_at": written_at,
            "build_started_at": written_at,
            "hour": hour,
            "day": day,
            "provenance": snapshot_provenance(expected, rows=day),
            "coverage": {
                "complete": True,
                "published": True,
                "membership": receipt_provenance(expected),
                "day": {
                    "complete": True,
                    "expected": expected,
                    "expected_count": len(expected),
                    "succeeded_count": len(expected),
                },
                "hour": {"complete": True, "hour_copied_from_day": True},
            },
        }
    )
