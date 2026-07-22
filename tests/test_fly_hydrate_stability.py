"""Fly hydrate stability — brain letter must not block the event loop."""

import asyncio

import pytest


def test_brain_letter_route_uses_thread_and_cache(monkeypatch):
    from internal.letter import routes as letter_routes

    calls = {"n": 0}

    def fake_build():
        calls["n"] += 1
        return {
            "status": "ok",
            "empty": False,
            "date": "2026-07-22",
            "pick": {"name": "Test"},
            "outlook": "ok",
            "trust_banner": {},
            "brain_ui_ready": False,
            "watchdog": {},
            "working": {"ready": False, "top_price_signals": []},
            "story_path": {"data_available": False, "steps": []},
            "markdown": "# test",
            "yesterday_outcome": None,
            "seed_strip": [],
            "desk_block": "desk",
            "source": "/api/letter/brain",
        }

    monkeypatch.setattr(letter_routes, "build_brain_letter", fake_build)
    monkeypatch.setattr(letter_routes, "_BRAIN_TTL", 60.0)
    letter_routes._BRAIN_CACHE["payload"] = None
    letter_routes._BRAIN_CACHE["at"] = 0.0

    first = asyncio.run(letter_routes.api_letter_brain())
    second = asyncio.run(letter_routes.api_letter_brain())
    assert first["pick"]["name"] == "Test"
    assert second["pick"]["name"] == "Test"
    assert calls["n"] == 1  # cached


def test_brain_letter_timeout_returns_quiet(monkeypatch):
    from internal.letter import routes as letter_routes

    def slow():
        import time

        time.sleep(0.2)
        return {"status": "ok"}

    monkeypatch.setattr(letter_routes, "build_brain_letter", slow)
    monkeypatch.setattr(letter_routes, "_BRAIN_TIMEOUT", 0.05)
    monkeypatch.setattr(letter_routes, "_BRAIN_TTL", 0.0)
    letter_routes._BRAIN_CACHE["payload"] = None
    letter_routes._BRAIN_CACHE["at"] = 0.0

    out = asyncio.run(letter_routes.api_letter_brain())
    assert out["status"] == "ok"
    assert out["empty"] is True
