"""Phase B2 — shared http_client helpers."""

from __future__ import annotations

import pytest

from internal import http_client


def test_sync_get_json_parses_response(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(http_client, "sync_get", lambda url, **kw: FakeResp())
    assert http_client.sync_get_json("https://example.test/api") == {"ok": True}


@pytest.mark.asyncio
async def test_async_get_json_cached_reuses_cache(monkeypatch):
    calls = []

    async def fake_async_get_json(url, **kw):
        calls.append(url)
        return {"n": len(calls)}

    monkeypatch.setattr(http_client, "async_get_json", fake_async_get_json)
    await http_client.async_get_json_cached.cache.clear()

    first = await http_client.async_get_json_cached("https://example.test/cached")
    second = await http_client.async_get_json_cached("https://example.test/cached")

    assert first == {"n": 1}
    assert second == {"n": 1}
    assert len(calls) == 1
