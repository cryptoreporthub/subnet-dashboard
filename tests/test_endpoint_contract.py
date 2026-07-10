"""Endpoint contract for the Subnet Dashboard API.

This is the guard the whole rebuild leans on: the app must expose every route
listed in CONTRACT, and each must respond without a server error (no 5xx) and
without being missing (no 404 for a route that should exist).

As feature slices are ported onto the FastAPI foundation (from the historical
``server_original.py``), add their routes here. A deploy should never promote a
build that regresses this contract.

Full target surface (47 routes) extracted from ``528ba62:server_original.py``;
routes not yet ported are tracked in NOT_YET_PORTED so we can see progress and
so nobody forgets them.
"""

import pytest
from fastapi.testclient import TestClient

from server import app


# (method, path, json_body) for routes that are LIVE now and must stay green.
CONTRACT = [
    ("GET", "/", None),
    ("GET", "/health", None),
    ("GET", "/api/daily-rotation", None),
    ("GET", "/api/registry", None),
    ("GET", "/api/subnets", None),
    ("GET", "/api/subnets?status=active&sort=emission&order=desc&limit=2", None),
    ("GET", "/api/subnet/1", None),
    ("GET", "/api/summary", None),
    ("GET", "/api/stats", None),
    ("GET", "/api/soul-map", None),
    ("GET", "/api/recommendations", None),
    ("POST", "/api/mindmap/feedback", {"note": "contract-test"}),
    # SimiVision picks (slice 2)
    ("GET", "/api/simivision", None),
    ("GET", "/api/top-picks", None),
    ("GET", "/api/daily-pick", None),
    ("GET", "/api/top-pick/day", None),
    ("GET", "/api/top-pick/hour", None),
]


# Remaining routes from the historical FastAPI monolith, to be ported in later
# slices. Kept here as a visible checklist (NOT asserted yet).
NOT_YET_PORTED = [
    "/api/health",
    "/api/freshness",
    "/api/rotation-tokens",
    "/api/pick-history",
    "/api/rotation-tracker",
    "/api/scenario-memory",
    "/api/judges",
    "/api/judges/{netuid}",
    "/api/judges/{judge}/postmortems",
    "/api/oracle",
    "/api/paper-portfolio",
    "/api/portfolios",
    "/api/postmortems",
    "/api/postmortems/{judge_name}",
    "/api/council/weights",
    "/api/weights",
    "/api/feedback",
    "/api/mindmap/summary",
    "/api/learning/stats",
    "/api/learning/trigger",
    "/api/learning-metrics",
    "/api/resolve-predictions",
    "/api/predictions",
    "/api/predictions/resolved",
    "/api/predictions/resolver",
    "/api/predictions/resolver/run",
    "/api/indicators",
    "/api/indicators-convergence",
    "/api/indicators/scheduler",
    "/api/price-tracking/baselines",
    "/api/price-tracking/outcomes",
    "/api/pump-analytics",
    "/api/simivision/chat",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("method,path,body", CONTRACT, ids=[f"{m} {p}" for m, p, _ in CONTRACT])
def test_contract_route_ok(client, method, path, body):
    if method == "GET":
        resp = client.get(path)
    elif method == "POST":
        resp = client.post(path, json=body)
    else:
        raise AssertionError(f"Unsupported method {method}")

    # Route must exist (not 404) and must not error (no 5xx).
    assert resp.status_code != 404, f"{method} {path} is missing (404)"
    assert resp.status_code < 500, f"{method} {path} returned {resp.status_code}"
    assert resp.status_code == 200, f"{method} {path} returned {resp.status_code}, expected 200"


def test_registered_routes_cover_contract():
    """Every GET/POST path in CONTRACT is actually registered on the app."""
    registered = set()
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        for m in methods:
            registered.add((m, getattr(route, "path", "")))
    for method, path, _ in CONTRACT:
        bare = path.split("?", 1)[0]
        # Path params render as {name} in the route table.
        template = bare.rsplit("/", 1)
        candidates = {bare}
        if template[-1].isdigit():
            candidates.add(template[0] + "/{subnet_id}")
        assert any((method, c) in registered for c in candidates), (
            f"{method} {bare} not registered on app"
        )
