"""Transport wrapper (gzip + immutable static cache), tested without importing server."""

from starlette.testclient import TestClient

from internal.transport import wrap

SSE_PATH = "/api/simivision/chat"
IMMUTABLE = "public, max-age=31536000, immutable"


async def _stub_app(scope, receive, send):
    if scope["type"] != "http":
        return
    path = scope.get("path", "")
    if path == SSE_PATH:
        headers = [(b"content-type", b"text/event-stream")]
        body = b"data: hello\n\n"
    elif path.startswith("/static/"):
        headers = [(b"content-type", b"text/plain")]
        body = b"body { color: red; }\n" * 100
    else:
        headers = [(b"content-type", b"text/plain")]
        body = b"hello world\n" * 100
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _client():
    return TestClient(wrap(_stub_app))


def test_gzip_applied_when_accepted():
    c = _client()
    r = c.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("Content-Encoding") == "gzip"
    assert r.content == b"hello world\n" * 100


def test_sse_not_gzipped():
    c = _client()
    r = c.post(SSE_PATH, json={"stream": True}, headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("Content-Encoding") in (None, "identity")
    assert r.text.startswith("data: hello")


def test_fingerprinted_static_gets_immutable(monkeypatch):
    from internal import transport as t

    monkeypatch.setattr(
        t, "_fingerprinted_static_paths", lambda: frozenset({"/static/css/ui.css"})
    )
    c = TestClient(t.wrap(_stub_app))
    r = c.get("/static/css/ui.css")
    assert r.headers["Cache-Control"] == IMMUTABLE


def test_unlisted_static_untouched():
    c = _client()
    r = c.get("/static/js/not_listed.js")
    assert r.headers.get("Cache-Control") != IMMUTABLE
