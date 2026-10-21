"""Typed JSON-RPC errors for pinned chain reads (#1395 Step 2)."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

RpcErrorKind = Literal[
    "archive_miss",
    "unknown_block",
    "rate_limited",
    "rpc_error",
    "invalid",
    "timeout",
    "connection",
    "parse",
]


class ChainRpcError(Exception):
    """Structured RPC failure for ``ChainClient._call_typed``."""

    def __init__(
        self,
        kind: RpcErrorKind,
        message: str = "",
        *,
        code: Optional[int] = None,
        retry_after: Optional[float] = None,
        http_status: Optional[int] = None,
    ):
        self.kind = kind
        self.code = code
        self.retry_after = retry_after
        self.http_status = http_status
        super().__init__(message or kind)


class PinnedBlockMismatch(ChainRpcError):
    """``state_queryStorageAt`` returned a different block than requested."""

    def __init__(self, requested: str, got: str):
        self.requested = requested
        self.got = got
        super().__init__(
            "invalid",
            f"pinned block mismatch requested={requested} got={got}",
        )


_DISCARDED_RE = re.compile(r"discarded|unknownblock", re.I)


def classify_jsonrpc_error(err: Any) -> RpcErrorKind:
    if not isinstance(err, dict):
        return "rpc_error"
    code = err.get("code")
    message = str(err.get("message") or "")
    lower = message.lower()
    if code == 4003 or (code == 1 and _DISCARDED_RE.search(lower)):
        return "archive_miss"
    if code == 4001 or "header was not found" in lower:
        return "unknown_block"
    if code == 429 or "429" in lower or "too many requests" in lower:
        return "rate_limited"
    if _DISCARDED_RE.search(lower):
        return "archive_miss"
    return "rpc_error"


def classify_http_status(status_code: int) -> RpcErrorKind:
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "rpc_error"
    return "rpc_error"


def normalize_block_hash(block_hash: str) -> str:
    return block_hash.lower().removeprefix("0x")


def storage_block_matches(entry: Any, block_hash: str) -> bool:
    """Fail closed: a pinned storage read must echo the requested block hash."""
    if not isinstance(entry, dict):
        return False
    returned = entry.get("block")
    if not returned:
        return False
    return normalize_block_hash(str(returned)) == normalize_block_hash(block_hash)
