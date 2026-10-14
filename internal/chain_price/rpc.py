"""RPC error classification for chain price sampling."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple

import requests

from internal.chain_rpc_errors import ChainRpcError, PinnedBlockMismatch, classify_jsonrpc_error
from internal.chain_price.outcomes import RpcOutcome

logger = logging.getLogger(__name__)


def classify_rpc_error(exc: BaseException) -> RpcOutcome:
    if isinstance(exc, PinnedBlockMismatch):
        return "invalid"
    if isinstance(exc, ChainRpcError):
        if exc.kind in ("archive_miss", "unknown_block", "rate_limited", "invalid", "rpc_error"):
            if exc.kind == "unknown_block":
                return "invalid"
            return exc.kind  # type: ignore[return-value]
        return "rpc_error"
    if isinstance(exc, requests.HTTPError):
        if exc.response is not None and exc.response.status_code == 429:
            return "rate_limited"
        return "rpc_error"
    if isinstance(exc, RuntimeError):
        err = exc.args[0] if exc.args else None
        if isinstance(err, dict):
            kind = classify_jsonrpc_error(err)
            if kind == "unknown_block":
                return "invalid"
            return kind  # type: ignore[return-value]
    message = str(exc).lower()
    if "4003" in message or "archive" in message or "discarded" in message:
        return "archive_miss"
    if "4001" in message or "header was not found" in message:
        return "invalid"
    if "429" in message:
        return "rate_limited"
    if "pinned block mismatch" in message:
        return "invalid"
    return "rpc_error"


def rpc_call(
    client: Any,
    method: str,
    params: Optional[list] = None,
) -> Tuple[Optional[Any], RpcOutcome]:
    params = params or []
    if method == "state_queryStorageAt" and len(params) >= 2:
        try:
            result = client.query_storage_at(params[0], params[1])
            return result, "ok"
        except Exception as exc:
            outcome = classify_rpc_error(exc)
            logger.debug("chain price rpc %s -> %s: %s", method, outcome, exc)
            return None, outcome
    if hasattr(client, "_call_typed"):
        try:
            result = client._call_typed(method, params)
            return result, "ok"
        except Exception as exc:
            outcome = classify_rpc_error(exc)
            logger.debug("chain price rpc %s -> %s: %s", method, outcome, exc)
            return None, outcome
    try:
        result = client._call(method, params)
        return result, "ok"
    except Exception as exc:
        outcome = classify_rpc_error(exc)
        logger.debug("chain price rpc %s -> %s: %s", method, outcome, exc)
        return None, outcome


def rpc_call_fn(client: Any) -> Callable[[str, list], Tuple[Optional[Any], RpcOutcome]]:
    def _inner(method: str, params: list) -> Tuple[Optional[Any], RpcOutcome]:
        return rpc_call(client, method, params)

    return _inner
