"""RPC error classification for chain price sampling."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple

import requests

from internal.chain_price.outcomes import RpcOutcome

logger = logging.getLogger(__name__)


def classify_rpc_error(exc: BaseException) -> RpcOutcome:
    if isinstance(exc, requests.HTTPError):
        if exc.response is not None and exc.response.status_code == 429:
            return "rate_limited"
        return "rpc_error"
    message = str(exc).lower()
    if "4003" in message or "archive" in message:
        return "archive_miss"
    if "429" in message:
        return "rate_limited"
    return "rpc_error"


def rpc_call(
    client: Any,
    method: str,
    params: Optional[list] = None,
) -> Tuple[Optional[Any], RpcOutcome]:
    try:
        result = client._call(method, params or [])
        return result, "ok"
    except Exception as exc:
        outcome = classify_rpc_error(exc)
        logger.debug("chain price rpc %s -> %s: %s", method, outcome, exc)
        return None, outcome


def rpc_call_fn(client: Any) -> Callable[[str, list], Tuple[Optional[Any], RpcOutcome]]:
    def _inner(method: str, params: list) -> Tuple[Optional[Any], RpcOutcome]:
        return rpc_call(client, method, params)

    return _inner
