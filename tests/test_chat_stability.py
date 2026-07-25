"""Prod stability — chat must not block on live subnet feeds."""

from unittest.mock import patch

from internal.simivision.chat_service import build_chat_context


def test_build_chat_context_uses_registry_not_live_feed():
    with patch("server._get_subnets_with_source") as live_feed:
        ctx = build_chat_context()
        live_feed.assert_not_called()
    assert ctx.get("simivision_picks") is not None
    assert ctx.get("source") == "registry-fallback"
    assert "soul_map" not in ctx


def test_build_chat_context_cached(monkeypatch):
    import internal.simivision.chat_service as chat

    monkeypatch.setattr(chat, "_CHAT_CONTEXT_CACHE", {"at": 0.0, "ctx": None})
    monkeypatch.setattr(chat, "_CHAT_CONTEXT_TTL", 60.0)
    calls = {"n": 0}
    orig_stats = chat.LearningEngine.get_stats

    def counted(self):
        calls["n"] += 1
        return orig_stats(self)

    monkeypatch.setattr(chat.LearningEngine, "get_stats", counted)
    build_chat_context()
    build_chat_context()
    assert calls["n"] == 1
