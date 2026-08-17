"""Focused dashboard cache, timing, and browser request-coalescing regressions."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server import app


def test_dashboard_routes_publish_server_timing():
    """Waterfall measurements are visible in browsers without another telemetry service."""
    response = TestClient(app).get("/api/top-picks")
    assert response.status_code == 200
    assert response.headers["server-timing"].startswith("app;dur=")


def test_top_picks_fresh_cache_skips_refresh(monkeypatch):
    import server as srv

    cached = {"hour_picks": [{"netuid": 1}], "day_picks": [{"netuid": 2}]}
    srv._TOP_PICKS_CACHE.update(payload=cached, at=time.time())
    monkeypatch.setattr(
        srv,
        "_build_top_picks",
        lambda: (_ for _ in ()).throw(AssertionError("fresh cache must skip scoring")),
    )
    assert srv._build_top_picks_cached() == cached


def test_top_picks_stale_cache_returns_data_while_refreshing(monkeypatch):
    import server as srv

    cached = {"hour_picks": [{"netuid": 7}], "day_picks": [{"netuid": 8}]}
    srv._TOP_PICKS_CACHE.update(payload=cached, at=time.time() - 999)
    srv._TOP_PICKS_BG_REFRESHING = False
    calls = {"count": 0}

    def kick():
        calls["count"] += 1

    monkeypatch.setattr(srv, "_kick_top_picks_background_refresh", kick)
    assert srv._build_top_picks_cached() == cached
    assert calls["count"] == 1


def test_dashboard_thread_timeout_keeps_event_loop_responsive():
    import server as srv

    def slow():
        time.sleep(0.2)
        return "late"

    async def run():
        started = time.monotonic()
        try:
            await srv._to_thread_timeout(slow, 0.01, label="test-dashboard-work")
        except asyncio.TimeoutError:
            return time.monotonic() - started
        raise AssertionError("expected soft deadline")

    assert asyncio.run(run()) < 0.1


def test_market_driver_snapshot_avoids_repeated_disk_scans(monkeypatch):
    from internal.analytics import market_drivers

    market_drivers._LEARNED_DRIVERS_CACHE.update(at=0.0, payload=None)
    calls = {"count": 0}

    def rows():
        calls["count"] += 1
        return []

    monkeypatch.setattr(market_drivers, "_gradeable_resolved", rows)
    first = market_drivers.learned_price_drivers()
    second = market_drivers.learned_price_drivers()

    assert first == second
    assert calls["count"] == 1


def test_homepage_fetch_layer_coalesces_same_url_requests():
    source = Path("static/js/api_fetch.js").read_text(encoding="utf-8")
    assert "var inFlight = {}" in source
    assert "var responseCache = {}" in source
    assert "if (inFlight[key]) return inFlight[key]" in source
    assert "delete inFlight[key]" in source


def test_hydration_keeps_daily_pick_available_before_deferred_secondary_batch():
    source = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    daily_index = source.index("window.HomeHydrateCache.dailyPick = lastDailyPickPayload")
    secondary_index = source.index("// Tier 2 — secondary panels")
    assert daily_index < secondary_index


def test_hydration_awaits_daily_pick_before_tribunal_stats_render():
    source = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    await_idx = source.index("var dpResult = await dailyPickRequest;")
    hero_idx = source.index("var heroDailyPick = lastDailyPickPayload || dpResult;")
    assert await_idx < hero_idx


def test_daily_pick_hydrate_bypasses_api_fetch_cache():
    source = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "fetchJsonRetry('/api/daily-pick', 35000, 3, 0)" in source