"""ASGI bailout must answer / and /health even when the inner app is wedged."""

import asyncio
import time

import httpx
import pytest

from internal.instant_bailout import HARDCODED_EMERGENCY_HTML, wrap_instant_bailout


async def _wedged_app(scope, receive, send):
    await asyncio.sleep(60)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"slow"})


def _run(coro):
    return asyncio.run(coro)


def test_bailout_health_instant_when_inner_wedged():
    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=lambda: None,
        schedule_warm=lambda: None,
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.time()
            resp = await client.get("/health")
            return resp, time.time() - t0

    resp, elapsed = _run(_check())
    assert resp.status_code == 200
    assert resp.text == "OK"
    assert elapsed < 1.0


def test_bailout_root_serves_hardcoded_emergency():
    warmed = []

    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=lambda: None,
        schedule_warm=lambda: warmed.append(True),
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.time()
            resp = await client.get("/")
            return resp, time.time() - t0

    resp, elapsed = _run(_check())
    assert resp.status_code == 200
    assert elapsed < 1.0
    assert "Loading council" in resp.text
    assert warmed == [True]


def test_bailout_root_prefers_cached_html():
    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=lambda: "<html><body>cached</body></html>",
        schedule_warm=lambda: pytest.fail("warm should not run on cache hit"),
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/")

    resp = _run(_check())
    assert resp.status_code == 200
    assert resp.text == "<html><body>cached</body></html>"


def test_hardcoded_emergency_has_inline_css():
    assert b"background:#0a0a0f" in HARDCODED_EMERGENCY_HTML
    assert b"location.reload" in HARDCODED_EMERGENCY_HTML
