"""Resolver missing-price retry semantics patch."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PATCH_ATTR = "_resolver_semantics_patch_applied"
_RETRY_CAP = max(1, int(os.environ.get("RESOLVER_PRICE_RETRY_CAP", "3")))
# The watchdog treats two horizon windows as the stale boundary. Keep the
# resolver's default expiry policy aligned so a missing-price row cannot remain
# pending after the watchdog has correctly declared it past grace.
_GRACE_MULTIPLE = float(os.environ.get("RESOLVER_EXPIRY_GRACE_MULTIPLE", "2.0"))


def apply_resolver_semantics_patch() -> None:
    import internal.council.resolver as resolver

    if getattr(resolver, _PATCH_ATTR, False):
        return
    setattr(resolver, _PATCH_ATTR, True)
    resolver._PRICE_RETRY_CAP = _RETRY_CAP
    resolver._EXPIRY_GRACE_MULTIPLE = _GRACE_MULTIPLE

    original_lookup_horizon_price = resolver.lookup_horizon_price
    original_expire_prediction = resolver._expire_prediction

    def _patched_is_expired(
        prediction: Dict[str, Any],
        resolve_at: datetime,
        now: datetime,
        grace_multiple: float = _GRACE_MULTIPLE,
    ) -> bool:
        if now < resolve_at:
            return False
        try:
            horizon = float(prediction.get("horizon_hours", 0) or 0)
        except (TypeError, ValueError):
            horizon = 0.0
        if horizon <= 0:
            horizon = float(getattr(resolver, "_EXPIRY_DEFAULT_HORIZON_HOURS", 24.0))
        grace_hours = horizon * grace_multiple

        # Retries are a best-effort recovery while a row remains inside its
        # grace window. Never let a missing-price retry create new pending work
        # after the watchdog's expiry deadline.
        if now >= resolve_at + timedelta(hours=grace_hours):
            return True

        attempts = int(prediction.get("resolve_attempts") or 0)
        # The second expiry check in one resolve pass must not consume the
        # final retry; the next scheduler tick gets the bounded final attempt.
        if prediction.pop("_price_lookup_attempted", False):
            return False
        # Give real ledger rows a bounded chance to obtain their historical
        # price before classifying them as genuine expiry.
        if attempts < _RETRY_CAP and ("id" in prediction or "resolve_at" in prediction):
            return False
        return False

    def _patched_lookup_horizon_price(
        prediction: Dict[str, Any],
        *,
        resolve_at: datetime,
        now: datetime,
        live_prices: Optional[Dict[Any, float]] = None,
        cache_path: Optional[str] = None,
    ) -> Tuple[str, float, Dict[str, Any]]:
        status, price, meta = original_lookup_horizon_price(
            prediction,
            resolve_at=resolve_at,
            now=now,
            live_prices=live_prices,
            cache_path=cache_path,
        )
        if status == "ok" and price > 0:
            prediction.pop("price_data_unavailable", None)
            return status, price, meta

        # A late cycle may still grade from a historical price, but an
        # ungradeable lookup at or beyond the deadline must retire immediately
        # rather than consuming a fourth, unusable retry.
        if resolver._is_expired(prediction, resolve_at, now):
            return status, price, meta

        prediction["resolve_attempts"] = int(prediction.get("resolve_attempts") or 0) + 1
        prediction["price_data_unavailable"] = True
        prediction["_price_lookup_attempted"] = True
        return status, price, meta

    def _patched_expire_prediction(prediction: Dict[str, Any], now: datetime) -> Dict[str, Any]:
        expired = original_expire_prediction(prediction, now)
        if prediction.get("price_data_unavailable"):
            expired["expired_reason"] = "price_data_unavailable"
            expired["retirement_reason"] = "missing_price_at_horizon"
        else:
            expired.setdefault("retirement_reason", "genuine_expiry")
        return expired

    resolver._is_expired = _patched_is_expired
    resolver.lookup_horizon_price = _patched_lookup_horizon_price
    resolver._expire_prediction = _patched_expire_prediction
    logger.info(
        "resolver missing-price retry semantics patch applied (cap=%s, grace=%.1f)",
        _RETRY_CAP,
        _GRACE_MULTIPLE,
    )
