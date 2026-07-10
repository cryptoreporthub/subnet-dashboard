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
    # Whale Intelligence (slice 3)
    ("GET", "/api/whales/summary", None),
    ("GET", "/api/whales/dimensions", None),
    ("GET", "/api/whales/leaderboards", None),
    ("GET", "/api/whales/leaderboards/ruggers", None),
    ("GET", "/api/whales/wallet/5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", None),
    ("GET", "/api/whales/alerts", None),
    ("GET", "/api/whales/subnet/1/flow", None),
    (
        "POST",
        "/api/whales/events",
        {
            "wallet": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            "netuid": 1,
            "side": "buy",
            "amount_tao": 100.0,
        },
    ),
    ("POST", "/api/whales/scan", {"netuids": [1], "top_n": 1}),
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


def _collect_registered_routes():
    """Collect (method, path) pairs from the app and any included routers."""
    registered = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", None)
        if path:
            for method in methods:
                registered.add((method, path))
        original = getattr(route, "original_router", None)
        if original is not None:
            stack.extend(original.routes)
    return registered


def _path_matches(contract_path: str, registered_path: str) -> bool:
    if contract_path == registered_path:
        return True
    contract_parts = contract_path.strip("/").split("/")
    registered_parts = registered_path.strip("/").split("/")
    if len(contract_parts) != len(registered_parts):
        return False
    return all(
        part.startswith("{") and part.endswith("}")
        or contract_part == part
        for contract_part, part in zip(contract_parts, registered_parts)
    )


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
    registered = _collect_registered_routes()
    for method, path, _ in CONTRACT:
        bare = path.split("?", 1)[0]
        candidates = {bare}
        template = bare.rsplit("/", 1)
        if template[-1].isdigit():
            candidates.add(template[0] + "/{subnet_id}")

        matched = any(
            reg_method == method and _path_matches(candidate, reg_path)
            for candidate in candidates
            for reg_method, reg_path in registered
        )
        assert matched, f"{method} {bare} not registered on app"
