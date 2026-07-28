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
    from internal.integrations.clients import clear_models_probe_cache
    from internal.simivision.chat_service import call_llm

    clear_models_probe_cache()
    monkeypatch.setenv("CHUTES_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.chutes.ai/v1")
    monkeypatch.delenv("CHUTES_BASE_URL", raising=False)
    seen: list[str] = []

    def _fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("/models"):
            class _R:
                status_code = 200

            return _R()
        if method == "POST" and url.endswith("/chat/completions"):
            seen.append(url)
            class _R:
                status_code = 200

                def json(self):
                    return {"choices": [{"message": {"content": "ok from chutes"}}]}

            return _R()
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr("internal.integrations.clients._request", _fake_request)
    reply, llm_used, provider = call_llm("prompt", "hello", {})
    assert llm_used is True
    assert provider == "chutes"
    assert reply == "ok from chutes"
    assert seen and seen[0].startswith("https://llm.chutes.ai/v1/chat/completions")


def test_call_llm_prefers_thirty_spokes_when_chutes_models_fail(monkeypatch):
    from internal.integrations.clients import clear_models_probe_cache
    from internal.simivision.chat_service import call_llm

    clear_models_probe_cache()
    monkeypatch.setenv("THIRTY_SPOKES_API_KEY", "test-key")
    monkeypatch.delenv("CHUTES_API_KEY", raising=False)
    seen: list[str] = []

    def _fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("/models"):
            if "llm.chutes.ai" in url:
                class _R:
                    status_code = 401

                return _R()
            if "thirtyspokes.ai" in url:
                class _R:
                    status_code = 200

                return _R()
        if method == "POST" and url.endswith("/chat/completions"):
            seen.append(url)
            class _R:
                status_code = 200

                def json(self):
                    return {"choices": [{"message": {"content": "from router"}}]}

            return _R()
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr("internal.integrations.clients._request", _fake_request)
    reply, llm_used, provider = call_llm("prompt", "hello", {})
    assert llm_used is True
    assert provider == "thirty_spokes"
    assert reply == "from router"
    assert seen and "thirtyspokes.ai" in seen[0]


def test_call_llm_chutes_model_fallback_to_default(monkeypatch):
    from internal.integrations.clients import clear_models_probe_cache
    from internal.simivision.chat_service import call_llm

    clear_models_probe_cache()
    monkeypatch.setenv("CHUTES_API_KEY", "test-key")
    monkeypatch.setenv("CHUTES_MODEL", "bad-model-id")
    models_seen: list[str] = []

    def _fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("/models"):
            class _R:
                status_code = 200

                def json(self):
                    return {"data": [{"id": "catalog-model"}]}

            return _R()
        if method == "POST" and url.endswith("/chat/completions"):
            body = kwargs.get("json_body") or kwargs.get("json") or {}
            model = body.get("model", "")
            models_seen.append(model)
            class _R:
                status_code = 200 if model in ("default", "catalog-model") else 400
                text = "bad model"

                def json(self):
                    return {"choices": [{"message": {"content": f"ok {model}"}}]}

            return _R()
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr("internal.integrations.clients._request", _fake_request)
    reply, llm_used, provider = call_llm("prompt", "hello", {})
    assert llm_used is True
    assert provider == "chutes"
    assert reply == "ok default"
    assert models_seen[0] == "bad-model-id"
    assert "default" in models_seen


def test_handle_chat_offline_when_key_configured_but_llm_fails(monkeypatch):
    import asyncio

    import internal.simivision.chat_service as chat

    monkeypatch.setenv("CHUTES_API_KEY", "test-key")
    monkeypatch.setattr(chat, "build_chat_context", lambda: {"source": "registry-fallback"})
    monkeypatch.setattr(chat, "_maybe_investigation_context", lambda _m: None)
    monkeypatch.setattr(chat, "call_llm", lambda *_a, **_k: ("local answer", False, ""))

    async def _run():
        return await chat.handle_simivision_chat("hello")

    out = asyncio.run(_run())
    assert out["status"] == "offline"
    assert out["model"] == "local-fallback"


def test_wants_investigation_generic_pick_question_false():
    from internal.simivision.chat_service import _wants_investigation

    assert not _wants_investigation("What is today's best subnet pick?")
    assert not _wants_investigation("Explain the council featured call")
    assert not _wants_investigation("Which subnet has the highest APY?")


def test_wants_investigation_on_chain_true():
    from internal.simivision.chat_service import _wants_investigation

    assert _wants_investigation("Who sold on SN29 today?")
    assert _wants_investigation("Trace transfers from 5HCFWvRqzSHWRPecN7q8J6c7aKQnrCZTMHstPv39xL1wgDHh")
    assert _wants_investigation("Is the subnet owner selling?")


def test_maybe_investigation_skipped_for_generic_pick(monkeypatch):
    import internal.simivision.chat_service as chat

    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("investigation should not run")

    monkeypatch.setattr(chat, "build_investigation_context", _boom)
    assert chat._maybe_investigation_context("What is today's featured council pick?") is None
    assert called["n"] == 0


def test_handle_chat_returns_status_local_fallback(monkeypatch):
    import internal.simivision.chat_service as chat

    monkeypatch.setattr(chat, "build_chat_context", lambda: {"source": "registry-fallback"})
    monkeypatch.setattr(chat, "_maybe_investigation_context", lambda _m: None)
    monkeypatch.setattr(chat, "call_llm", lambda *_a, **_k: ("local answer", False, ""))

    async def _run():
        return await chat.handle_simivision_chat("hello")

    import asyncio

    out = asyncio.run(_run())
    assert out["status"] == "local-fallback"
    assert out["model"] == "local-fallback"


def test_handle_chat_generic_pick_within_budget(monkeypatch):
    """Wave D4 — generic pick question must not block on investigation or slow LLM."""
    import asyncio
    import time

    import internal.simivision.chat_service as chat

    monkeypatch.setattr(
        chat,
        "build_chat_context",
        lambda: {"source": "registry-fallback", "simivision_picks": []},
    )
    monkeypatch.setattr(chat, "_maybe_investigation_context", lambda _m: None)
    monkeypatch.setattr(
        chat,
        "call_llm",
        lambda *_a, **_k: ("Featured SN64 leads on emission today.", True, "chutes"),
    )

    async def _run():
        return await chat.handle_simivision_chat("What is today's featured council pick?")

    start = time.monotonic()
    out = asyncio.run(_run())
    elapsed = time.monotonic() - start
    assert out["status"] == "ok"
    assert out["model"].startswith("chutes/")
    assert elapsed < 2.0


def test_chat_contract_route_generic_pick_within_budget(monkeypatch):
    """POST /api/simivision/chat stays under 8s when LLM path is mocked fast."""
    import time

    from fastapi.testclient import TestClient

    import internal.simivision.chat_service as chat
    from server import app

    monkeypatch.setattr(chat, "build_chat_context", lambda: {"source": "registry-fallback"})
    monkeypatch.setattr(chat, "_maybe_investigation_context", lambda _m: None)
    monkeypatch.setattr(
        chat,
        "call_llm",
        lambda *_a, **_k: ("Quick council summary.", True, "chutes"),
    )

    with TestClient(app) as client:
        start = time.monotonic()
        resp = client.post(
            "/api/simivision/chat",
            json={"message": "What is the top subnet pick today?"},
        )
        elapsed = time.monotonic() - start

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert elapsed < 8.0


def test_call_llm_skips_slow_chutes_when_thirty_spokes_models_ok(monkeypatch):
    """Do not wait on Chutes completions when /models says only Thirty Spokes is live."""
    import time

    from internal.integrations.clients import clear_models_probe_cache
    from internal.simivision.chat_service import call_llm

    clear_models_probe_cache()
    monkeypatch.setenv("THIRTY_SPOKES_API_KEY", "test-key")
    monkeypatch.delenv("CHUTES_API_KEY", raising=False)

    def _fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("/models"):
            if "llm.chutes.ai" in url:
                class _R:
                    status_code = 401

                return _R()
            if "thirtyspokes.ai" in url:
                class _R:
                    status_code = 200

                return _R()
        if method == "POST" and url.endswith("/chat/completions"):
            if "llm.chutes.ai" in url:
                time.sleep(0.5)
                class _R:
                    status_code = 401
                    text = "nope"

                    def json(self):
                        return {}

                return _R()
            class _R:
                status_code = 200

                def json(self):
                    return {"choices": [{"message": {"content": "router wins"}}]}

            return _R()
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr("internal.integrations.clients._request", _fake_request)
    start = time.monotonic()
    reply, llm_used, provider = call_llm("prompt", "hello", {})
    elapsed = time.monotonic() - start
    assert llm_used is True
    assert provider == "thirty_spokes"
    assert reply == "router wins"
    assert elapsed < 0.4
