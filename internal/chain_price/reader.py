"""Multi-provider chain reader with fallback (#1395 Step 2)."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from internal.chain_client import (
    ChainClient,
    _clear_rate_limit_step,
    note_rate_limit,
    rate_limited_until,
)
from internal.chain_price import config as cfg
from internal.chain_price.outcomes import RpcOutcome
from internal.chain_price.rpc import classify_rpc_error, rpc_call
from internal.chain_rpc_errors import storage_block_matches

_FULL_BLOCK_HASH = re.compile(r"0x[0-9a-fA-F]{64}")


def _is_full_block_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_FULL_BLOCK_HASH.fullmatch(value))

logger = logging.getLogger(__name__)


class ChainReader:
    """Ordered RPC providers; pin each tick to one block hash."""

    def __init__(
        self,
        clients: Optional[List[Tuple[str, ChainClient]]] = None,
        *,
        deadline_monotonic: Optional[float] = None,
    ):
        self._providers: List[Tuple[str, ChainClient]] = clients or cfg.rpc_provider_clients()
        self._pinned_hash: Optional[str] = None
        # Per thread, and set only while pin_finalized_head_strict runs on that thread: ``call`` then
        # treats a finalized head that is not a full 64-hex hash as an invalid answer, so provider
        # fallback applies to it. Thread-local, so a shared reader used by another thread at the same
        # time keeps its lenient pin.
        self._strict_state = threading.local()
        self.provider_served: Optional[str] = None
        self.fallback_count: int = 0
        self.rate_limit_events: List[Dict[str, Any]] = []
        self._deadline_monotonic = deadline_monotonic
        if deadline_monotonic is not None:
            for _, client in self._providers:
                client._rpc_deadline_monotonic = deadline_monotonic

    @property
    def _strict_pin(self) -> bool:
        return getattr(self._strict_state, "on", False)

    @_strict_pin.setter
    def _strict_pin(self, value: bool) -> None:
        self._strict_state.on = value

    def _past_deadline(self) -> bool:
        deadline = self._deadline_monotonic
        return deadline is not None and time.monotonic() >= deadline

    def reset_probe_diagnostics(self) -> None:
        """Clear per-run probe counters (Step 4 live harness)."""
        self.fallback_count = 0
        self.rate_limit_events = []
        self.provider_served = None

    def _available_providers(self) -> List[Tuple[str, ChainClient]]:
        now = time.monotonic()
        out: List[Tuple[str, ChainClient]] = []
        for label, client in self._providers:
            endpoint = getattr(client, "endpoint", None)
            if endpoint and rate_limited_until(endpoint) > now:
                continue
            out.append((label, client))
        return out

    def _mark_rate_limited(
        self,
        label: str,
        client: ChainClient,
        *,
        http_status: Optional[int] = None,
    ) -> None:
        endpoint = getattr(client, "endpoint", None)
        if not endpoint:
            logger.warning("chain reader provider %s rate limited (no endpoint)", label)
            return
        duration = note_rate_limit(endpoint)
        event: Dict[str, Any] = {"provider": label, "http_status": http_status}
        self.rate_limit_events.append(event)
        logger.warning(
            "chain reader provider %s rate limited (http_status=%s); endpoint cooldown %.0fs",
            label,
            http_status,
            duration,
        )

    def _should_fallback(self, outcome: RpcOutcome) -> bool:
        # Any invalid answer (bad echo, unknown block, pin mismatch) is one provider's answer,
        # so the next provider gets a try. The fail-closed echo check still gates each result.
        return outcome in ("rpc_error", "archive_miss", "rate_limited", "invalid")

    @staticmethod
    def _echo_mismatch(method: str, params: list, result: Any) -> bool:
        """A pinned state read must echo the block hash it was asked for."""
        if method != "state_queryStorageAt" or not isinstance(params, list) or len(params) < 2:
            return False
        if not isinstance(params[1], str) or not isinstance(result, list) or not result:
            return False
        return not storage_block_matches(result[0], params[1])

    def call(self, method: str, params: list) -> Tuple[Optional[Any], RpcOutcome]:
        if self._past_deadline():
            return None, "rpc_error"
        providers = self._available_providers()
        if not providers:
            self.rate_limit_events.append(
                {"provider": None, "http_status": None, "reason": "all_providers_cooldown"}
            )
            return None, "rate_limited"
        last_outcome: RpcOutcome = "rpc_error"
        for idx, (label, client) in enumerate(providers):
            if self._past_deadline():
                return None, "rpc_error"
            result, outcome = rpc_call(client, method, params)
            if outcome == "ok" and self._echo_mismatch(method, params, result):
                outcome = "invalid"
            if (
                outcome == "ok"
                and self._strict_pin
                and method == "chain_getFinalizedHead"
                and not _is_full_block_hash(result)
            ):
                outcome = "invalid"  # one provider's malformed head: the next provider gets a try
            if outcome == "rate_limited":
                rl_http = getattr(client, "_last_rate_limit_http_status", None)
                self._mark_rate_limited(label, client, http_status=rl_http)
            if outcome == "ok":
                endpoint = getattr(client, "endpoint", None)
                if endpoint:
                    _clear_rate_limit_step(endpoint)
                self.provider_served = label
                return result, outcome
            last_outcome = outcome
            if not self._should_fallback(outcome) or idx == len(providers) - 1:
                return None, outcome
            self.fallback_count += 1
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

    def pin_finalized_head_strict(self) -> Tuple[Optional[str], RpcOutcome]:
        """``pin_finalized_head`` that only accepts a full 64-hex block hash.

        Membership is stamped with this block and later admitted only if it is a full pin, so a
        storage layer that echoes a truncated or malformed head (``0x1234``) must be refused here,
        before any netuid read at that block can enter the universe. The check runs inside the
        provider loop, so a malformed head from one provider falls back to the next provider; only
        when every provider answers malformed is the pin refused (``invalid``). Other callers (the
        price sampler) keep the lenient ``pin_finalized_head``.

        Production always takes this path: ``read_chain_membership`` calls it on every real
        ``ChainReader``, and ``SnapshotBuilder`` builds its own reader. A bare reader double that only
        has ``pin_finalized_head`` is read loosely on purpose: main's tests/test_subnet_universe.py
        pins the registration read with the literal block "0xabc" through such a double and must
        pass unedited. Nothing loose is ever admitted: receipt provenance, completeness and reload
        all parse the block strictly.
        """
        self._strict_pin = True
        try:
            block_hash, outcome = self.pin_finalized_head()
        finally:
            self._strict_pin = False
        # Defence in depth for a replaced/patched pin_finalized_head that bypassed ``call``.
        if outcome == "ok" and block_hash and not _is_full_block_hash(block_hash):
            outcome, block_hash = "invalid", None
        if outcome != "ok" or not block_hash:
            self._pinned_hash = None  # a refused pin is not left behind from an earlier read
            return None, outcome if outcome != "ok" else "absent"
        return block_hash, outcome

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

    def provider_states(self) -> List[Tuple[str, Optional[str]]]:
        """Configured providers as (label, endpoint) for ops visibility."""
        return [
            (label, getattr(client, "endpoint", None))
            for label, client in self._providers
        ]


_reader_singleton: Optional[ChainReader] = None


def get_shared_reader() -> ChainReader:
    global _reader_singleton
    if _reader_singleton is None:
        _reader_singleton = ChainReader()
    return _reader_singleton


def reset_shared_reader() -> None:
    global _reader_singleton
    _reader_singleton = None
