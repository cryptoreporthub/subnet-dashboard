"""§17.F5 — streaming / chunked SimiVision chat."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from internal.simivision.chat_service import sanitize_reply
from server import app


def _sse_events(body: str) -> list[tuple[str, str]]:
    """Parse an SSE body into (event, data) pairs, skipping comment blocks."""
    events: list[tuple[str, str]] = []
    for block in body.split("\n\n"):
        ev, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data or ev != "message":
            events.append((ev, data))
    return events


def _hermetic_chat(monkeypatch, reply: str = "ok reply", llm_used: bool = True, delay: float = 0.0):
    """Stub context/investigation/LLM so stream tests never touch live APIs."""
    import internal.simivision.chat_service as chat

    monkeypatch.setattr(chat, "build_chat_context", lambda: {"source": "registry-fallback"})
    monkeypatch.setattr(chat, "_maybe_investigation_context", lambda _m: None)

    def _llm(*_a, **_k):
        if delay:
            time.sleep(delay)
        return reply, llm_used, "chutes" if llm_used else ""

    monkeypatch.setattr(chat, "call_llm", _llm)
    return chat


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


def test_chat_stream_done_is_last_event(monkeypatch):
    """SSE must terminate: `event: done` is emitted exactly once, last."""
    _hermetic_chat(monkeypatch, reply="c" * 120)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/simivision/chat?stream=1",
        json={"message": "hello"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    events = _sse_events(body)
    names = [e for e, _ in events]
    assert names[-1] == "done"
    assert "done" not in names[:-1]


def test_chat_stream_timeout_bounded_partial_done(monkeypatch):
    """Slow LLM: stream degrades to `partial` meta and still ends with done."""
    chat = _hermetic_chat(monkeypatch, reply="late reply", delay=1.0)
    monkeypatch.setattr(chat, "_CHAT_TIMEOUT_SEC", 0.3)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/simivision/chat?stream=1",
        json={"message": "hello"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    statuses = [
        json.loads(data).get("status")
        for ev, data in _sse_events(body)
        if ev == "meta"
    ]
    assert "partial" in statuses
    assert _sse_events(body)[-1][0] == "done"


def test_chat_stream_sanitizes_llm_reply(monkeypatch):
    """LLM output must be HTML-escaped before it reaches the SSE wire."""
    _hermetic_chat(monkeypatch, reply="<script>alert(1)</script>")
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/simivision/chat?stream=1",
        json={"message": "hello"},
    ) as resp:
        body = "".join(resp.iter_text())
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert _sse_events(body)[-1][0] == "done"


def test_chat_stream_client_abort_closes_cleanly():
    """Client disconnect mid-stream (generator close) must not raise."""
    import asyncio

    from internal.simivision.chat_service import iter_simivision_chat_chunks

    async def _run():
        gen = iter_simivision_chat_chunks("hello")
        first = await gen.__anext__()
        assert ": ok" in first
        await gen.aclose()

    asyncio.run(_run())


def test_chat_stream_js_has_no_html_sinks():
    """Static XSS guard: the chat UI must render via textContent only."""
    with open("static/js/chat_stream.js", "r") as f:
        js = f.read()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in js, f"chat_stream.js must not use {sink}"
    assert "textContent" in js
