"""Outermost ASGI bailout — answer GET / and /health before FastAPI can wedge.

Fly returns 0-byte 503 when the worker never responds (~36s). Sync routes,
lifespan Jinja priming, and a saturated Starlette thread pool can block the
entire app including StaticFiles. This layer short-circuits the hot paths.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

# Inline critical CSS — no /static dependency on first paint.
HARDCODED_EMERGENCY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#080a10">
<title>SimiVision — Council</title>
<meta property="og:image" content="/static/og-share.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="/static/og-share.png">
<style>
  html,body{margin:0;min-height:100%;background:#0a0a0f;color:#e8e8f0;
    font-family:system-ui,-apple-system,sans-serif}
  .wrap{max-width:28rem;margin:0 auto;padding:2.5rem 1.25rem;text-align:center}
  h1{font-size:1.35rem;font-weight:600;letter-spacing:.02em;margin:0 0 .75rem}
  p{margin:0;opacity:.78;font-size:.95rem;line-height:1.45}
  .pulse{animation:pulse 1.4s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.45}}
  .nfa{margin:1.25rem auto 0;max-width:28rem;padding:0 1.25rem;font-size:.68rem;line-height:1.4;color:#7a9186;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <h1 class="pulse">Loading council…</h1>
  <p>Subnet dashboard is warming up. If this stays blank, tap refresh.</p>
</div>
<p class="nfa">SimiVision calls are scored council output, not financial advice. Do your own research.</p>
</body>
</html>
""".encode("utf-8")

# Critical hydrate assets — served without touching the inner app when the loop is wedged.
_BAILOUT_STATIC_ALLOWLIST: dict[str, str] = {
    "/static/js/cockpit_hydrate.js": "application/javascript",
    "/static/js/mindmap_graph.js": "application/javascript",
    "/static/js/api_fetch.js": "application/javascript",
    "/static/css/ui.css": "text/css",
}
_BAILOUT_STATIC_CACHE_CONTROL = b"public, max-age=60"


def _default_static_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def _preload_bailout_static(static_dir: str) -> dict[str, bytes]:
    loaded: dict[str, bytes] = {}
    for url_path in _BAILOUT_STATIC_ALLOWLIST:
        rel = url_path.removeprefix("/static/").replace("/", os.sep)
        file_path = os.path.join(static_dir, rel)
        try:
            with open(file_path, "rb") as fh:
                loaded[url_path] = fh.read()
        except OSError:
            continue
    return loaded


async def _send_response(
    send,
    *,
    status: int,
    body: bytes,
    content_type: str,
    cache_control: bytes = b"no-store, max-age=0",
    extra_headers: Optional[list[tuple[bytes, bytes]]] = None,
) -> None:
    from internal.security_headers import security_header_items

    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", content_type.encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", cache_control),
    ]
    for name, value in security_header_items():
        headers.append((name.lower().encode("ascii"), value.encode("utf-8")))
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class InstantBailoutASGI:
    """Serve / and /health without calling the inner app when possible."""

    def __init__(
        self,
        app,
        *,
        get_homepage_html: Callable[[], Optional[str]],
        schedule_warm: Callable[[], None],
        homepage_cache_control: bytes = b"no-store, max-age=0",
        static_dir: Optional[str] = None,
    ) -> None:
        self.app = app
        self._get_homepage_html = get_homepage_html
        self._schedule_warm = schedule_warm
        self._homepage_cache_control = homepage_cache_control
        self._bailout_static = _preload_bailout_static(static_dir or _default_static_dir())

    def __getattr__(self, name: str):
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")

        if method == "GET" and path == "/api/ops/live":
            from internal.ops.readiness import build_liveness_report

            body = json.dumps(build_liveness_report(probe_worker=False)).encode("utf-8")
            await _send_response(send, status=200, body=body, content_type="application/json; charset=utf-8")
            return

        if method == "GET" and path == "/health":
            await _send_response(send, status=200, body=b"OK", content_type="text/plain; charset=utf-8")
            return

        if method == "GET" and path == "/api/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            await _send_response(send, status=200, body=body, content_type="application/json; charset=utf-8")
            return

        if method == "GET" and path in self._bailout_static:
            content_type = _BAILOUT_STATIC_ALLOWLIST[path]
            await _send_response(
                send,
                status=200,
                body=self._bailout_static[path],
                content_type=f"{content_type}; charset=utf-8",
                cache_control=_BAILOUT_STATIC_CACHE_CONTROL,
            )
            return

        if method == "GET" and path == "/":
            html = self._get_homepage_html()
            if html:
                await _send_response(
                    send,
                    status=200,
                    body=html.encode("utf-8"),
                    content_type="text/html; charset=utf-8",
                    cache_control=self._homepage_cache_control,
                )
                return
            self._schedule_warm()
            await _send_response(
                send,
                status=200,
                body=HARDCODED_EMERGENCY_HTML,
                content_type="text/html; charset=utf-8",
                cache_control=self._homepage_cache_control,
            )
            return

        await self.app(scope, receive, send)


def wrap_instant_bailout(
    app,
    *,
    get_homepage_html,
    schedule_warm,
    homepage_cache_control: bytes = b"no-store, max-age=0",
    static_dir: Optional[str] = None,
):
    return InstantBailoutASGI(
        app,
        get_homepage_html=get_homepage_html,
        schedule_warm=schedule_warm,
        homepage_cache_control=homepage_cache_control,
        static_dir=static_dir,
    )
