"""
Regression: GET /api/daily-pick's timeout shed must not serve a prior-day
stashed payload as today's pick.

Prod symptom (2026-08-31): the 2026-08-30 scheduler HOLD (date=2026-08-30,
generated_at 2026-08-30T00:33:51Z, _meta.stale=False) was served all day
because the asyncio.TimeoutError branch shed to _DAILY_PICK_STASH with no
date check.
"""

from __future__ import annotations

import asyncio
import time

import pytest


def _seed_hold(date: str) -> dict:
    return {
        "status": "ok",
        "date": date,
        "action": "HOLD",
        "pick": None,
        "candidate": {"subnet": {"netuid": 114, "name": "SOMA"}},
    }


@pytest.mark.parametrize(
    "payload_kind, expect_shed",
    [
        ("stale-date", False),
        ("same-day", True),
    ],
)
def test_daily_pick_timeout_shed_date_guard(monkeypatch, payload_kind, expect_shed):
    """Timeout shed reuses the stash ONLY for today's stored pick (UTC)."""
    import server as srv

    from internal.council.daily_pick_engine import _today_str

    date = _today_str() if payload_kind == "same-day" else "2000-01-01"
    seeded = _seed_hold(date)
    srv._DAILY_PICK_STASH["payload"] = seeded

    def _slow_hydrate(stash):
        time.sleep(0.2)
        return seeded

    monkeypatch.setattr(srv, "_hydrate_daily_pick_lite", _slow_hydrate)
    monkeypatch.setattr(srv, "PICK_READ_TIMEOUT", 0.05)

    body = asyncio.run(srv.api_daily_pick())

    if expect_shed:
        assert body.get("date") == _today_str()
        assert body.get("action") == "HOLD"
    else:
        assert body is not seeded
        assert body.get("date") != "2000-01-01"
        assert str(body.get("status") or "").lower() == "timeout"
        assert (body.get("_meta") or {}).get("stale") is True
