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


def test_chutes_llm_base_url_rewrites_api_chutes_ai(monkeypatch):
    from internal.integrations.clients import chutes_llm_base_url

    monkeypatch.setenv("LLM_BASE_URL", "https://api.chutes.ai/v1")
    monkeypatch.delenv("CHUTES_BASE_URL", raising=False)
    assert chutes_llm_base_url() == "https://llm.chutes.ai/v1"


def test_call_llm_uses_llm_chutes_when_llm_base_is_api_chutes(monkeypatch):
    from internal.simivision.chat_service import call_llm

    monkeypatch.setenv("CHUTES_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.chutes.ai/v1")
    monkeypatch.delenv("CHUTES_BASE_URL", raising=False)
    seen: list[str] = []

    def _fake_post(url, **kwargs):
        seen.append(url)
        class _R:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "ok from chutes"}}]}

        return _R()

    monkeypatch.setattr("requests.post", _fake_post)
    reply, llm_used = call_llm("prompt", "hello", {})
    assert llm_used is True
    assert reply == "ok from chutes"
    assert seen and seen[0].startswith("https://llm.chutes.ai/v1/chat/completions")
