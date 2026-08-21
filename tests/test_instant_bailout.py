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
    assert b"location.reload" not in HARDCODED_EMERGENCY_HTML


def test_bailout_homepage_cold_returns_instant_shell_without_blocking():
    """Cold bailout must not sync-render Jinja — that wedges /health on Fly."""
    import server as srv

    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._EMERGENCY_HOME_HTML = ""
    t0 = time.monotonic()
    html = srv._bailout_homepage_html()
    elapsed = time.monotonic() - t0
    assert html == srv._INSTANT_HOME_SHELL
    assert elapsed < 0.5


def test_bailout_health_instant_when_homepage_prime_would_hang():
    import server as srv
    from unittest.mock import patch

    def _hang_prime():
        time.sleep(30)

    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=srv._bailout_homepage_html,
        schedule_warm=lambda: None,
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            srv._HOMEPAGE_HTML_CACHE["html"] = None
            srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
            srv._EMERGENCY_HOME_HTML = ""
            with patch.object(srv, "_prime_emergency_home_html", side_effect=_hang_prime):
                t0 = time.time()
                health = await client.get("/health")
                root = await client.get("/")
                return health, root, time.time() - t0

    health, root, elapsed = _run(_check())
    assert health.status_code == 200
    assert health.text == "OK"
    assert root.status_code == 200
    # Cold path must answer instantly even if Jinja prime hangs.
    assert elapsed < 1.0
    assert "Loading council" in root.text or 'id="tribunal-hero"' in root.text


def test_bailout_static_allowlist_served_when_inner_wedged():
    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=lambda: None,
        schedule_warm=lambda: None,
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.time()
            resp = await client.get("/static/js/mindmap_graph.js?v=abc123")
            return resp, time.time() - t0

    resp, elapsed = _run(_check())
    assert resp.status_code == 200
    assert elapsed < 1.0
    assert "application/javascript" in resp.headers.get("content-type", "")
    assert len(resp.content) > 100
    assert b"function" in resp.content or b"const" in resp.content or b"var" in resp.content


def test_bailout_static_allowlist_includes_hydrate_assets():
    app = wrap_instant_bailout(
        _wedged_app,
        get_homepage_html=lambda: None,
        schedule_warm=lambda: None,
    )
    transport = httpx.ASGITransport(app=app)

    async def _check():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            hydrate = await client.get("/static/js/cockpit_hydrate.js")
            css = await client.get("/static/css/ui.css")
            return hydrate, css

    hydrate, css = _run(_check())
    assert hydrate.status_code == 200
    assert css.status_code == 200
    assert "text/css" in css.headers.get("content-type", "")
