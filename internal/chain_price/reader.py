"""Multi-provider chain reader with fallback (#1395 Step 2)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_client import ChainClient
from internal.chain_price import config as cfg
from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.rpc import classify_rpc_error, rpc_call

logger = logging.getLogger(__name__)

_COOLDOWN_INITIAL_SECONDS = 600.0
_COOLDOWN_MAX_SECONDS = 3600.0


class ChainReader:
    """Ordered RPC providers; pin each tick to one block hash."""

    def __init__(self, clients: Optional[List[Tuple[str, ChainClient]]] = None):
        self._providers: List[Tuple[str, ChainClient]] = clients or cfg.rpc_provider_clients()
        self._cooldown_until: Dict[str, float] = {}
        self._cooldown_seconds: Dict[str, float] = {}
        self._pinned_hash: Optional[str] = None
        self.provider_served: Optional[str] = None

    def _available_providers(self) -> List[Tuple[str, ChainClient]]:
        now = time.time()
        out: List[Tuple[str, ChainClient]] = []
        for label, client in self._providers:
            until = self._cooldown_until.get(label, 0.0)
            if now >= until:
                out.append((label, client))
        return out

    def _mark_rate_limited(self, label: str) -> None:
        prev = self._cooldown_seconds.get(label)
        if prev is None:
            self._cooldown_seconds[label] = _COOLDOWN_INITIAL_SECONDS
        else:
            self._cooldown_seconds[label] = min(prev * 2.0, _COOLDOWN_MAX_SECONDS)
        self._cooldown_until[label] = time.time() + self._cooldown_seconds[label]
        logger.warning(
            "chain reader provider %s rate limited; cooldown %.0fs",
            label,
            self._cooldown_seconds[label],
        )

    def _should_fallback(self, outcome: RpcOutcome) -> bool:
        return outcome in ("rpc_error", "archive_miss", "rate_limited")

    def call(self, method: str, params: list) -> Tuple[Optional[Any], RpcOutcome]:
        providers = self._available_providers()
        if not providers:
            return None, "rate_limited"
        last_outcome: RpcOutcome = "rpc_error"
        for idx, (label, client) in enumerate(providers):
            result, outcome = rpc_call(client, method, params)
            if outcome == "rate_limited":
                self._mark_rate_limited(label)
            if outcome == "ok":
                self.provider_served = label
                return result, outcome
            last_outcome = outcome
            if not self._should_fallback(outcome) or idx == len(providers) - 1:
                return None, outcome
            logger.info(
                "chain reader fallback after %s on %s for %s",
                outcome,
                label,
                method,
            )
        return None, last_outcome

    def call_fn(self) -> Callable[[str, list], Tuple[Optional[Any], RpcOutcome]]:
        return self.call

    def pin_finalized_head(self) -> Tuple[Optional[str], RpcOutcome]:
        block_hash, outcome = self.call("chain_getFinalizedHead", [])
        if outcome == "ok" and block_hash:
            self._pinned_hash = str(block_hash)
        return (str(block_hash) if block_hash else None), outcome

    @property
    def pinned_hash(self) -> Optional[str]:
        return self._pinned_hash

    def reset_pin(self) -> None:
        self._pinned_hash = None
        self.provider_served = None

    def active_client(self) -> Optional[ChainClient]:
        if self.provider_served:
            for label, client in self._providers:
                if label == self.provider_served:
                    return client
        if self._providers:
            return self._providers[0][1]
        return None


_reader_singleton: Optional[ChainReader] = None


def get_shared_reader() -> ChainReader:
    global _reader_singleton
    if _reader_singleton is None:
        _reader_singleton = ChainReader()
    return _reader_singleton


def reset_shared_reader() -> None:
    global _reader_singleton
    _reader_singleton = None
