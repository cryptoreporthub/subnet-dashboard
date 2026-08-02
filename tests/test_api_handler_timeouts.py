"""Regression: bare thread-offload handlers must return degraded JSON on timeout."""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from internal.judges import council_routes
from internal.letter import routes as letter_routes
from server import app


def test_api_judges_timeout_returns_degraded(monkeypatch):
    """Cold miss returns busy immediately — request path never blocks on scoring."""
    council_routes._JUDGES_CACHE["payload"] = None
    council_routes._JUDGES_CACHE["at"] = 0.0
    council_routes._BG_REFRESHING.clear()
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)
    kicked = {"n": 0}

    def _kick(cache, lock, build):
        kicked["n"] += 1

    monkeypatch.setattr(council_routes, "_kick_background_refresh", _kick)

    t0 = time.time()
    resp = TestClient(app).get("/api/judges")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 1.0
    assert resp.json() == {
        "success": False,
        "error": "busy",
        "judges": [],
        "count": 0,
    }
    assert kicked["n"] == 1


def test_api_judges_timeout_returns_stale_cache(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)
    stale = {"success": True, "judges": [{"netuid": 7}], "count": 1, "source": "registry"}
    council_routes._JUDGES_CACHE["payload"] = stale
    council_routes._JUDGES_CACHE["at"] = time.time() - 999
    council_routes._BG_REFRESHING.clear()
    monkeypatch.setattr(council_routes, "_kick_background_refresh", lambda *a, **k: None)

    def _slow():
        time.sleep(2)
        return {"success": True, "judges": [{"netuid": 1}], "count": 1}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _slow)
    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json() == stale


def test_api_judges_ttl_miss_serves_stale_immediately(monkeypatch):
    monkeypatch.setattr(council_routes, "JUDGES_HANDLER_TIMEOUT", 0.05)
    stale = {"success": True, "judges": [{"netuid": 7}], "count": 1, "source": "registry"}
    council_routes._JUDGES_CACHE["payload"] = stale
    council_routes._JUDGES_CACHE["at"] = time.time() - 999
    council_routes._BG_REFRESHING.clear()
    kicked = {"n": 0}
    monkeypatch.setattr(
        council_routes,
        "_kick_background_refresh",
        lambda *a, **k: kicked.__setitem__("n", kicked["n"] + 1),
    )

    def _slow():
        time.sleep(2)
        return {"success": True, "judges": [{"netuid": 1}], "count": 1}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _slow)
    started = time.time()
    resp = TestClient(app).get("/api/judges")
    elapsed = time.time() - started
    assert resp.status_code == 200
    assert resp.json() == stale
    assert elapsed < 0.5
    assert kicked["n"] == 1


def test_api_judges_cold_miss_does_not_score_on_request_path(monkeypatch):
    council_routes._JUDGES_CACHE["payload"] = None
    council_routes._JUDGES_CACHE["at"] = 0.0
    council_routes._BG_REFRESHING.clear()
    called = {"score": 0}

    def _score(*a, **k):
        called["score"] += 1
        return []

    monkeypatch.setattr("internal.judges.subnet_judges.score_all_subnets", _score)
    monkeypatch.setattr(council_routes, "_kick_background_refresh", lambda *a, **k: None)

    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json()["error"] == "busy"
    assert called["score"] == 0


def test_api_judges_fresh_cache_returns_without_scoring(monkeypatch):
    cached = {"success": True, "judges": [{"netuid": 3}], "count": 1}
    council_routes._JUDGES_CACHE["payload"] = cached
    council_routes._JUDGES_CACHE["at"] = time.time()
    called = {"score": 0}

    def _score(*a, **k):
        called["score"] += 1
        return []

    monkeypatch.setattr("internal.judges.subnet_judges.score_all_subnets", _score)
    resp = TestClient(app).get("/api/judges")
    assert resp.status_code == 200
    assert resp.json() == cached
    assert called["score"] == 0


def test_score_all_judges_request_path_use_chain_false(monkeypatch):
    seen = {}

    def _score(subnets, market_context=None, use_chain=True):
        seen["use_chain"] = use_chain
        return [{"netuid": 1, "consensus": {"score": 0.5}}]

    monkeypatch.setattr("internal.judges.subnet_judges.score_all_subnets", _score)
    council_routes._score_all_judges([{"netuid": 1, "emission": 1.0}])
    assert seen.get("use_chain") is False


def test_api_learning_health_timeout_returns_degraded(monkeypatch):
    import asyncio

    import httpx

    import internal.learning.loop_health as loop_health
    import internal.learning.routes as learning_routes

    monkeypatch.setattr(learning_routes, "LEARNING_HEALTH_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "ok", "pending": 0}

    monkeypatch.setattr(loop_health, "build_learning_loop_health", _slow)

    async def _fetch():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.time()
            resp = await client.get("/api/learning/health")
            return resp, time.time() - t0

    resp, elapsed = asyncio.run(_fetch())

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("meta", {}).get("source") == "timeout"
    assert body.get("error") == "timeout"
    assert elapsed < 1.0


def test_learning_health_ok_while_judges_blocked(monkeypatch):
    council_routes._JUDGES_CACHE["payload"] = None
    council_routes._JUDGES_CACHE["at"] = 0.0
    council_routes._BG_REFRESHING.clear()
    gate = threading.Event()

    def _block():
        gate.wait(timeout=5)
        return {"success": True, "judges": [], "count": 0}

    monkeypatch.setattr(council_routes, "_api_judges_sync_inner", _block)

    client = TestClient(app)
    judges_thread = threading.Thread(target=lambda: client.get("/api/judges"))
    judges_thread.start()
    time.sleep(0.05)

    health = client.get("/api/learning/health")
    gate.set()
    judges_thread.join(timeout=5)

    assert health.status_code == 200
    body = health.json()
    assert "status" in body
    assert body.get("error") != "timeout"


def test_api_simivision_cold_miss_returns_busy_immediately(monkeypatch):
    import server as srv

    srv._SIMIVISION_CACHE["payload"] = None
    srv._SIMIVISION_CACHE["at"] = 0.0
    srv._SIMIVISION_BG_REFRESHING = False
    kicked = {"n": 0}

    def _kick():
        kicked["n"] += 1

    monkeypatch.setattr(srv, "_kick_simivision_background_refresh", _kick)

    t0 = time.time()
    resp = TestClient(app).get("/api/simivision")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert elapsed < 1.0
    body = resp.json()
    assert body.get("meta", {}).get("source") == "busy"
    assert body.get("top") == []
    assert kicked["n"] == 1


def test_api_simivision_ttl_miss_serves_stale_immediately(monkeypatch):
    import server as srv

    stale = {"top": [{"netuid": 7, "name": "cached"}], "meta": {"count": 1, "source": "cache"}}
    srv._SIMIVISION_CACHE["payload"] = stale
    srv._SIMIVISION_CACHE["at"] = time.time() - 999
    srv._SIMIVISION_BG_REFRESHING = False
    kicked = {"n": 0}
    monkeypatch.setattr(
        srv, "_kick_simivision_background_refresh", lambda: kicked.__setitem__("n", kicked["n"] + 1)
    )

    t0 = time.time()
    resp = TestClient(app).get("/api/simivision")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert resp.json() == stale
    assert elapsed < 0.5
    assert kicked["n"] == 1


def test_simivision_bg_timeout_writes_degraded_and_clears_flag(monkeypatch):
    """Hung build must not pin BG_REFRESHING — cache a degraded board and clear."""
    import server as srv

    srv._SIMIVISION_CACHE["payload"] = None
    srv._SIMIVISION_CACHE["at"] = 0.0
    srv._SIMIVISION_BG_REFRESHING = False
    monkeypatch.setattr(srv, "_SIMIVISION_BG_BUILD_TIMEOUT", 0.05)

    def _hang():
        time.sleep(2)
        return {"status": "success", "data": {"top": [{"netuid": 1}], "meta": {}}}

    monkeypatch.setattr(srv, "_simivision_build_inner", _hang)

    srv._kick_simivision_background_refresh()
    deadline = time.time() + 3
    while time.time() < deadline and srv._SIMIVISION_BG_REFRESHING:
        time.sleep(0.05)

    assert srv._SIMIVISION_BG_REFRESHING is False
    cached = srv._SIMIVISION_CACHE.get("payload")
    assert isinstance(cached, dict)
    data = cached.get("data") if isinstance(cached.get("data"), dict) else cached
    assert data.get("top") == []
    assert (data.get("meta") or {}).get("source") == "bg-timeout"


def test_simivision_bg_success_clears_flag(monkeypatch):
    import server as srv

    srv._SIMIVISION_CACHE["payload"] = None
    srv._SIMIVISION_CACHE["at"] = 0.0
    srv._SIMIVISION_BG_REFRESHING = False
    warm = {
        "status": "success",
        "data": {"top": [{"netuid": 9, "name": "ok"}], "meta": {"count": 1, "source": "test"}},
    }
    monkeypatch.setattr(srv, "_simivision_build_inner", lambda: warm)

    srv._kick_simivision_background_refresh()
    deadline = time.time() + 3
    while time.time() < deadline and srv._SIMIVISION_BG_REFRESHING:
        time.sleep(0.05)

    assert srv._SIMIVISION_BG_REFRESHING is False
    assert srv._SIMIVISION_CACHE.get("payload") == warm


def test_api_mindmap_summary_single_flight_busy(monkeypatch):
    from internal.learning import routes as learning_routes

    learning_routes._MINDMAP_SUMMARY_CACHE["payload"] = None
    learning_routes._MINDMAP_SUMMARY_CACHE["at"] = 0.0
    learning_routes._MINDMAP_SUMMARY_REFRESHING = False
    monkeypatch.setattr(learning_routes, "MINDMAP_SUMMARY_TIMEOUT", 30.0)
    gate = threading.Event()

    def _slow():
        gate.wait(timeout=5)
        return {"status": "success", "data": {"dpick": {"shortlist": [{"netuid": 1}]}}}

    monkeypatch.setattr(learning_routes, "_build_mindmap_summary", _slow)

    client = TestClient(app)
    first = threading.Thread(target=lambda: client.get("/api/mindmap/summary"))
    first.start()
    time.sleep(0.05)

    t0 = time.time()
    resp = client.get("/api/mindmap/summary")
    elapsed = time.time() - t0
    gate.set()
    first.join(timeout=5)

    assert resp.status_code == 200
    assert elapsed < 1.0
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("meta", {}).get("source") == "busy"


def test_api_mindmap_summary_single_flight_serves_stale(monkeypatch):
    from internal.learning import routes as learning_routes

    stale = {
        "status": "success",
        "data": {"dpick": {"shortlist": [{"netuid": 7}]}},
        "meta": {"source": "cache"},
    }
    learning_routes._MINDMAP_SUMMARY_CACHE["payload"] = stale
    learning_routes._MINDMAP_SUMMARY_CACHE["at"] = time.time() - 999
    learning_routes._MINDMAP_SUMMARY_REFRESHING = False
    # Avoid leftover/bg writers racing the assertion (request path must not wait on build).
    monkeypatch.setattr(learning_routes, "_kick_mindmap_summary_refresh", lambda: None)

    t0 = time.time()
    resp = TestClient(app).get("/api/mindmap/summary")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert resp.json() == stale
    assert elapsed < 0.5


def test_api_mindmap_summary_does_not_call_get_or_create_today_pick(monkeypatch):
    from internal.learning import routes as learning_routes

    def _boom(*_args, **_kwargs):
        raise AssertionError("get_or_create_today_pick must not run on mindmap summary")

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _boom,
    )
    monkeypatch.setattr(
        "internal.learning.dpick_shortlist.build_deliberation_shortlist",
        _boom,
    )

    learning_routes._build_mindmap_summary()

    learning_routes._MINDMAP_SUMMARY_CACHE["payload"] = None
    learning_routes._MINDMAP_SUMMARY_CACHE["at"] = 0.0
    learning_routes._MINDMAP_SUMMARY_REFRESHING = False
    monkeypatch.setattr(learning_routes, "_kick_mindmap_summary_refresh", lambda: None)

    resp = TestClient(app).get("/api/mindmap/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("meta", {}).get("source") == "busy"


def test_api_mindmap_summary_cold_miss_returns_busy_immediately(monkeypatch):
    from internal.learning import routes as learning_routes

    learning_routes._MINDMAP_SUMMARY_CACHE["payload"] = None
    learning_routes._MINDMAP_SUMMARY_CACHE["at"] = 0.0
    learning_routes._MINDMAP_SUMMARY_REFRESHING = False
    kicked = {"n": 0}

    def _kick():
        kicked["n"] += 1

    monkeypatch.setattr(learning_routes, "_kick_mindmap_summary_refresh", _kick)

    t0 = time.time()
    resp = TestClient(app).get("/api/mindmap/summary")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert elapsed < 1.0
    body = resp.json()
    assert body.get("status") == "degraded"
    assert body.get("meta", {}).get("source") == "busy"
    assert body.get("data", {}).get("dpick", {}).get("shortlist") == []
    assert kicked["n"] == 1


def test_api_mindmap_summary_ttl_miss_serves_stale_immediately(monkeypatch):
    from internal.learning import routes as learning_routes

    stale = {
        "status": "success",
        "data": {"dpick": {"shortlist": [{"netuid": 7}]}},
        "meta": {"source": "cache"},
    }
    learning_routes._MINDMAP_SUMMARY_CACHE["payload"] = stale
    learning_routes._MINDMAP_SUMMARY_CACHE["at"] = time.time() - 999
    learning_routes._MINDMAP_SUMMARY_REFRESHING = False
    kicked = {"n": 0}
    monkeypatch.setattr(
        learning_routes, "_kick_mindmap_summary_refresh", lambda: kicked.__setitem__("n", kicked["n"] + 1)
    )

    t0 = time.time()
    resp = TestClient(app).get("/api/mindmap/summary")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert resp.json() == stale
    assert elapsed < 0.5
    assert kicked["n"] == 1


def test_api_letter_weekly_timeout_returns_degraded(monkeypatch):
    monkeypatch.setattr(letter_routes, "LETTER_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "ok", "empty": False, "week_of": "2026-01-01", "markdown": "x"}

    monkeypatch.setattr(letter_routes, "build_weekly_letter", _slow)
    resp = TestClient(app).get("/api/letter/weekly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "timeout"
    assert body["empty"] is True
    assert body["markdown"] == ""


def test_api_mindmap_state_timeout_returns_degraded(monkeypatch):
    import internal.learning.mindmap_aggregator as agg
    import internal.learning.routes as learning_routes

    monkeypatch.setattr(agg, "_STATE_CACHE", {"at": 0.0, "payload": None})
    monkeypatch.setattr(learning_routes, "MINDMAP_STATE_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "success", "trail": [{"netuid": 1}], "trail_count": 1}

    monkeypatch.setattr(
        "internal.learning.mindmap_aggregator.build_mindmap_state", _slow
    )
    resp = TestClient(app).get("/api/mindmap/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "timeout"
    assert body["trail"] == []
    assert body["summaries"] == {}


def test_api_mindmap_state_timeout_serves_stale_cache(monkeypatch):
    import internal.learning.mindmap_aggregator as agg
    import internal.learning.routes as learning_routes

    stale = {
        "status": "success",
        "trail": [{"netuid": 7}],
        "trail_count": 1,
        "summaries": {"council": {"text": "cached"}},
    }
    monkeypatch.setattr(agg, "_STATE_CACHE", {"at": time.time() - 999, "payload": stale})
    monkeypatch.setattr(learning_routes, "MINDMAP_STATE_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "success", "trail": [], "trail_count": 0}

    monkeypatch.setattr("internal.learning.mindmap_aggregator.build_mindmap_state", _slow)
    resp = TestClient(app).get("/api/mindmap/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cached"
    assert body["trail"] == stale["trail"]


def test_api_mindmap_graph_timeout_returns_degraded(monkeypatch):
    import internal.mindmap.routes as graph_routes

    monkeypatch.setattr(graph_routes, "MINDMAP_GRAPH_HANDLER_TIMEOUT", 0.05)
    monkeypatch.setattr(graph_routes, "_cache", {})
    monkeypatch.setattr(graph_routes, "_build_locks", {})

    def _slow(focus=None):
        time.sleep(2)
        return {"status": "success", "nodes": [{"id": "sn:1"}], "edges": []}

    monkeypatch.setattr(graph_routes, "_cached_or_build", _slow)
    resp = TestClient(app).get("/api/mindmap/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "timeout"
    assert body["nodes"] == []


def test_api_mindmap_graph_timeout_serves_stale_cache(monkeypatch):
    import internal.mindmap.routes as graph_routes

    monkeypatch.setattr(graph_routes, "MINDMAP_GRAPH_HANDLER_TIMEOUT", 0.05)
    stale = {
        "status": "success",
        "nodes": [{"id": "sn:7", "kind": "subnet"}],
        "edges": [],
        "integration_status": {"council_trail": "closed"},
    }
    monkeypatch.setattr(
        graph_routes,
        "_cache",
        {None: {"at": time.time() - 999, "data": stale}},
    )
    monkeypatch.setattr(graph_routes, "_build_locks", {})

    def _slow(focus=None):
        time.sleep(2)
        return {"status": "success", "nodes": [{"id": "sn:1"}], "edges": []}

    monkeypatch.setattr(graph_routes, "_cached_or_build", _slow)
    resp = TestClient(app).get("/api/mindmap/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cached"
    assert body["nodes"] == stale["nodes"]


def test_api_mindmap_story_path_timeout_returns_degraded(monkeypatch):
    import internal.learning.routes as learning_routes

    monkeypatch.setattr(learning_routes, "_STORY_PATH_CACHE", {"at": 0.0, "payload": None})
    monkeypatch.setattr(learning_routes, "MINDMAP_STORY_PATH_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {
            "status": "success",
            "data_available": True,
            "steps": [{"id": "signals"}],
        }

    monkeypatch.setattr(learning_routes, "_build_mindmap_story_path", _slow)
    resp = TestClient(app).get("/api/mindmap/story-path")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "timeout"
    assert body["data_available"] is False
    assert body["steps"] == []


def test_api_mindmap_story_path_timeout_serves_stale_cache(monkeypatch):
    import internal.learning.routes as learning_routes

    stale = {
        "status": "success",
        "data_available": True,
        "steps": [{"id": "council", "title": "BUY Foo"}],
    }
    monkeypatch.setattr(
        learning_routes,
        "_STORY_PATH_CACHE",
        {"at": time.time() - 999, "payload": stale},
    )
    monkeypatch.setattr(learning_routes, "MINDMAP_STORY_PATH_HANDLER_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2)
        return {"status": "success", "data_available": True, "steps": []}

    monkeypatch.setattr(learning_routes, "_build_mindmap_story_path", _slow)
    resp = TestClient(app).get("/api/mindmap/story-path")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cached"
    assert body["steps"] == stale["steps"]
