"""Lightweight Telegram listener entitlements.

This is intentionally beta-local: it reuses request/session signals when
available and avoids introducing a billing or payment system.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


TIERS = ("free", "pro", "pro_plus")


@dataclass(frozen=True)
class Entitlement:
    tier: str = "free"
    beta_bypass: bool = False

    @property
    def is_free(self) -> bool:
        return self.tier == "free"

    @property
    def is_pro(self) -> bool:
        return self.tier in ("pro", "pro_plus")

    @property
    def is_pro_plus(self) -> bool:
        return self.tier == "pro_plus"


def beta_bypass_enabled() -> bool:
    return os.environ.get("TELEGRAM_LISTENER_BETA_BYPASS", "").strip().lower() in ("1", "true", "yes", "on")


def entitlement_from_user(user: Optional[Dict[str, Any]]) -> Entitlement:
    if beta_bypass_enabled():
        return Entitlement(tier="pro_plus", beta_bypass=True)
    if not isinstance(user, dict):
        return Entitlement()
    tier = str(user.get("tier") or user.get("plan") or "free").strip().lower().replace("-", "_")
    if tier not in TIERS:
        tier = "free"
    return Entitlement(tier=tier, beta_bypass=False)


def entitlement_from_request(request: Any = None, user: Optional[Dict[str, Any]] = None) -> Entitlement:
    if beta_bypass_enabled():
        return Entitlement(tier="pro_plus", beta_bypass=True)
    if isinstance(user, dict):
        return entitlement_from_user(user)
    if request is not None:
        try:
            session = getattr(request, "session", None) or {}
        except AssertionError:
            session = {}
        if isinstance(session, dict) and session.get("user"):
            return entitlement_from_user(session.get("user"))
        state_user = getattr(getattr(request, "state", None), "user", None)
        if isinstance(state_user, dict):
            return entitlement_from_user(state_user)
    return Entitlement()


def entitlement_payload(ent: Entitlement) -> Dict[str, Any]:
    return {
        "tier": ent.tier,
        "beta_bypass": ent.beta_bypass,
        "free": ent.is_free,
        "pro": ent.is_pro,
        "pro_plus": ent.is_pro_plus,
    }
