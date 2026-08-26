"""Homepage SSR/warm must read daily pick from JSON — never score or write."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_home_hero_context_does_not_call_get_or_create_today_pick(monkeypatch):
    import server as srv

    def _boom(*_a, **_k):
        raise AssertionError("get_or_create_today_pick must not run on homepage hero")

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _boom,
    )
    monkeypatch.setattr(srv, "get_or_create_today_pick", _boom)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine._find_today",
        lambda _rows: {
            "action": "HOLD",
            "candidate": {"subnet": {"netuid": 42, "name": "SN42"}},
        },
    )

    hero = srv._home_hero_context([{"netuid": 1}])
    assert isinstance(hero.get("daily_pick_stage"), dict)
    assert hero["daily_pick_stage"].get("action") == "HOLD"
    assert "tribunal" in hero
    assert "story_path" in hero


def test_pick_sections_does_not_call_get_or_create_today_pick(monkeypatch):
    import server as srv

    def _boom(*_a, **_k):
        raise AssertionError("get_or_create_today_pick must not run on pick_sections")

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _boom,
    )
    monkeypatch.setattr(srv, "get_or_create_today_pick", _boom)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine._find_today",
        lambda _rows: {
            "pick": {
                "subnet": {"netuid": 9, "name": "Gamma"},
                "score": 0.8,
                "confidence": 0.7,
            },
        },
    )

    from internal.learning.dashboard_context import _pick_sections

    with patch("server._ordered_hour_picks", return_value=[]):
        picks = _pick_sections([], {})

    assert picks["day_picks"]
    assert picks["day_picks"][0]["netuid"] == 9


def test_homepage_warm_does_not_call_get_or_create_today_pick(monkeypatch):
    """Degraded warm shell (_shell_pump_and_picks + _fast_home_hero_context)."""
    import server as srv

    def _boom(*_a, **_k):
        raise AssertionError("get_or_create_today_pick must not run on homepage warm")

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _boom,
    )
    monkeypatch.setattr(srv, "get_or_create_today_pick", _boom)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine._find_today",
        lambda _rows: {
            "action": "HOLD",
            "candidate": {"subnet": {"netuid": 14, "name": "SN14"}},
        },
    )

    def _degraded_only(request):
        raise RuntimeError("force degraded")

    monkeypatch.setattr(srv, "_build_index_context", _degraded_only)
    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._HOMEPAGE_WARMING = False
    srv._warm_homepage_cache(None)

    with TestClient(srv.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
