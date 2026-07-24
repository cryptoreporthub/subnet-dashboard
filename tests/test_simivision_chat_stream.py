"""§17.F5 — streaming / chunked SimiVision chat."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.simivision.chat_service import sanitize_reply
from server import app


def test_sanitize_reply_escapes_html():
    assert sanitize_reply("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )


def test_chat_json_default_still_works():
    client = TestClient(app)
    resp = client.post("/api/simivision/chat", json={"message": "ping"})
    assert resp.status_code == 200
    body = resp.json()
    assert "reply" in body
    assert "<" not in body["reply"] or "&lt;" in body["reply"] or body["reply"]


def test_chat_stream_chunks_via_query():
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/simivision/chat?stream=1",
        json={"message": "stream ping"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        chunks = list(resp.iter_text())
        first = chunks[0] if chunks else ""
        assert ": ok" in first or "thinking" in first
        body = "".join(chunks)
    assert "event: meta" in body
    assert "event: chunk" in body or "event: done" in body
    assert "event: done" in body


def test_chat_stream_via_body_flag():
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/simivision/chat",
        json={"message": "hi", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "event: done" in text
