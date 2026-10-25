"""An explicit ``grace_multiple`` must be honoured by ``resolver._is_expired`` (#1506)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def resolver():
    import internal.council.resolver as resolver_mod

    return resolver_mod


RESOLVE_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_explicit_huge_grace_bypasses_expiry(resolver):
    pred = {"horizon_hours": 1}
    now = RESOLVE_AT + timedelta(hours=100)

    assert resolver._is_expired(pred, RESOLVE_AT, now, 1_000_000.0) is False


def test_explicit_grace_of_two_expires_at_two_horizons(resolver):
    pred = {"horizon_hours": 1}

    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=1.9), 2.0) is False
    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=2), 2.0) is True


def test_row_without_horizon_hours_keeps_the_24h_default_grace(resolver):
    pred = {"horizon_type": "hour"}

    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=5)) is False
    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96)) is True
