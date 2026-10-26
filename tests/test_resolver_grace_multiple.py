"""An explicit ``grace_multiple`` must be honoured by ``resolver._is_expired`` (#1506)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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


def test_finite_huge_grace_does_not_overflow_the_expiry_window(resolver):
    row = {"id": 1, "horizon_hours": 24, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(days=365), 1e308) is False


def test_non_finite_horizon_falls_back_to_the_default_horizon(resolver):
    row = {"id": 1, "horizon_hours": float("inf"), "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=95), 4.0) is False
    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96), 4.0) is True


def test_env_huge_grace_is_used_without_raising_on_a_ledger_row():
    probe = (
        "import internal.council.resolver as r;"
        "from datetime import datetime, timedelta, timezone;"
        "t = datetime(2026, 8, 9, 12, tzinfo=timezone.utc);"
        "row = {'id': 1, 'horizon_hours': 24, 'resolve_attempts': r._PRICE_RETRY_CAP};"
        "print(r._is_expired(row, t, t + timedelta(days=365)))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env={**os.environ, "RESOLVER_EXPIRY_GRACE_MULTIPLE": "1e308"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.strip().splitlines()[-1] == "False"
