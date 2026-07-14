"""C2 — SSE cockpit stream for live section hydration."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from server import app


def test_cockpit_stream_once_emits_sections_snapshot():
    client = TestClient(app)
    with client.stream("GET", "/api/cockpit/stream?once=1") as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"
        body = "".join(resp.iter_text())

    assert "event: cockpit.sections" in body
    assert "retry: 15000" in body

    data_line = next(line for line in body.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    assert payload["type"] == "cockpit.sections"
    assert payload["version"] == 1
    assert payload["status"] == "success"
    assert payload["emitted_at"].endswith("Z")
    assert len(payload["sections"]) == 12
