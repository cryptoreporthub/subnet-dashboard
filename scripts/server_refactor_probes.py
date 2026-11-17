"""Bug probes for docs/server-refactor-plan.md (Appendix A and F).

Usage: PYTHONPATH=. python scripts/server_refactor_probes.py
Each P line is one measured behavior. The fix PRs turn each probe into a test.
The learning-loop recorders are stubbed, so the probes write no data files.
"""
import os, sys, time, json, asyncio
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
from datetime import datetime, timezone
print("P1 timestamp:", datetime.now(timezone.utc).isoformat() + "Z")
import server
from fastapi.testclient import TestClient
inner = server.app
routes = [(r.path, sorted(getattr(r, "methods", []) or [])) for r in inner.routes]
print("ROUTES total:", len(routes), "| defined in server.py module:", sum(1 for r in inner.routes if getattr(getattr(r, "endpoint", None), "__module__", "") == "server"))
print("app type chain:", type(server.app).__name__)
c = TestClient(server.app, raise_server_exceptions=False)

def p(label, fn):
    try: print(label, fn())
    except Exception as e: print(label, "PROBE-ERROR", type(e).__name__, e)

# P2: timeout payload gets a public cache header
def p2():
    orig_t, orig_b = server.SUBNETS_HANDLER_TIMEOUT, server._list_subnets_base_rows
    server._SUBNETS_CACHE.update(payload=None, at=0.0)
    server.SUBNETS_HANDLER_TIMEOUT = 0.05
    server._list_subnets_base_rows = lambda: (time.sleep(1.0), {"items": [], "feed_meta": {}})[1]
    try:
        r = c.get("/api/subnets")
        return (r.status_code, r.json().get("status"), r.json()["meta"].get("handler_status"), r.headers.get("cache-control"))
    finally:
        server.SUBNETS_HANDLER_TIMEOUT, server._list_subnets_base_rows = orig_t, orig_b
p("P2 /api/subnets on timeout ->", p2)

# P3: /api/stats vs /api/summary with staking_data None
def p3():
    orig = server._list_subnets_base_rows
    server._list_subnets_base_rows = lambda: {"items": [{"id": 1, "netuid": 1, "name": "x", "status": "active", "staking_data": None}], "feed_meta": {}}
    try:
        return ("stats", c.get("/api/stats").status_code, "summary", c.get("/api/summary").status_code)
    finally:
        server._list_subnets_base_rows = orig
p("P3 staking_data=None ->", p3)

# P3b: stats/summary bypass the subnets cache
def p3b():
    orig = server._list_subnets_base_rows; n = {"c": 0}
    def counted():
        n["c"] += 1; return {"items": [], "feed_meta": {}}
    server._list_subnets_base_rows = counted
    try:
        for _ in range(3): c.get("/api/stats"); c.get("/api/summary")
        return f"6 requests -> {n['c']} full rebuilds"
    finally:
        server._list_subnets_base_rows = orig
p("P3b", p3b)

# P5: simivision response shapes
def p5():
    server._SIMIVISION_CACHE.update(payload=None, at=0.0)
    orig = server._kick_simivision_background_refresh
    server._kick_simivision_background_refresh = lambda: None
    try: cold = sorted(c.get("/api/simivision").json().keys())
    finally: server._kick_simivision_background_refresh = orig
    server._SIMIVISION_CACHE.update(payload={"status": "success", "data": {"top": [], "meta": {}}}, at=time.time())
    warm = sorted(c.get("/api/simivision").json().keys())
    server._SIMIVISION_CACHE.update(payload=None, at=0.0)
    return {"cold_keys": cold, "warm_keys": warm}
p("P5 /api/simivision shapes ->", p5)

# P6: feedback endpoint on a non-JSON body
p("P6 POST /api/mindmap/feedback bad body ->", lambda: (lambda r: (r.status_code, r.text[:120]))(c.post("/api/mindmap/feedback", content=b"not json")))

# P7: error responses are HTTP 200 and echo the exception text
def p7():
    orig = server._get_subnets_with_source
    def boom(**k): raise RuntimeError("secret /app/data/path leaked")
    server._get_subnets_with_source = boom
    try:
        r = c.get("/api/pick-explain/5"); return (r.status_code, r.json())
    finally: server._get_subnets_with_source = orig
p("P7 /api/pick-explain on failure ->", p7)

# P8: feed failure -> fabricated static rows -> learning-loop recorder, from a GET path
def p8():
    import internal.subnets.feed as feed, internal.learning.prediction_loop as pl
    from internal.council import pick_history
    captured = []
    o1, o2, o3, o4 = feed.get_council_subnet_feed, pl.record_pick_prediction, pl.record_hold_decision, pick_history.record_hour_pick
    def fail(**k): raise RuntimeError("feed down")
    feed.get_council_subnet_feed = fail
    pl.record_pick_prediction = lambda pick, subnet, **k: captured.append(("prediction", subnet.get("name"), subnet.get("price"), k.get("shadow", False))) or {"id": "x"}
    pl.record_hold_decision = lambda **k: captured.append(("hold", (k.get("subnet") or {}).get("name"), (k.get("subnet") or {}).get("price"), False))
    pick_history.record_hour_pick = lambda *a, **k: captured.append(("pick_history", a[1].get("name"), a[1].get("price"), False))
    try:
        subnets, src = server._get_subnets_with_source()
        mc = server._market_context_with_weights(subnets)
        server._ordered_hour_picks(subnets, mc, limit=3)
        return {"source": src, "rows": [(s["name"], s["price"]) for s in subnets], "recorded": captured}
    finally:
        feed.get_council_subnet_feed, pl.record_pick_prediction, pl.record_hold_decision, pick_history.record_hour_pick = o1, o2, o3, o4
p("P8 static fallback ->", p8)

# P9: homepage cold path renders on the event loop
import inspect
src = inspect.getsource(server.index)
print("P9 index() is async:", asyncio.iscoroutinefunction(server.index), "| calls _ultra_minimal_index_html inline:", "_ultra_minimal_index_html()" in src and "run_in_executor" not in src and "to_thread" not in src)
print("P10 cache TTL defaults: _CACHE_PATHS['/']=", server._CACHE_PATHS["/"], "HOMEPAGE_SHELL_CACHE_SECONDS=", server.HOMEPAGE_SHELL_CACHE_SECONDS)
