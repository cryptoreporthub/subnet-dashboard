"""Typed outcomes for chain price RPC and tick results."""

from __future__ import annotations

from typing import Literal, TypedDict

TickOutcome = Literal[
    "ok",
    "absent",
    "invalid",
    "archive_miss",
    "rate_limited",
    "rpc_error",
    "schema_miss",
    "bucket_incomplete",
    "disabled",
    "disk_low",
    "db_unavailable",
]

RpcOutcome = Literal[
    "ok",
    "absent",
    "invalid",
    "archive_miss",
    "rate_limited",
    "rpc_error",
    "timeout",
    "connection",
    "parse",
]


class TickResult(TypedDict, total=False):
    outcome: TickOutcome
    provider: str
    block: int
    block_hash: str
    ts_ms: int
    n_subnets: int
    samples_written: int
    spot_crosscheck_failures: int
    error: str
