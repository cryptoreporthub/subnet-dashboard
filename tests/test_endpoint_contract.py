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
    # Council / judges (slice 4)
    ("GET", "/api/judges", None),
    ("GET", "/api/judges/1", None),
    ("GET", "/api/judges/oracle/postmortems", None),
    ("GET", "/api/paper-portfolio", None),
    ("GET", "/api/portfolios", None),
    ("GET", "/api/postmortems", None),
    ("GET", "/api/postmortems/oracle", None),
    ("GET", "/api/council", None),
    # Learning loop read APIs (slice 5)
    ("GET", "/api/mindmap/summary", None),
    ("GET", "/api/learning/stats", None),
    ("GET", "/api/learning-metrics", None),
    ("GET", "/api/predictions", None),
    ("GET", "/api/predictions/resolved", None),
    ("GET", "/api/predictions/resolver", None),
    # Ruggers watchlist facade (slice 4b — backward-compat over whales)
    ("GET", "/api/ruggers/summary", None),
    ("GET", "/api/ruggers/watchlist", None),
    ("GET", "/api/ruggers/watchlist/5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY", None),
    ("GET", "/api/ruggers/alerts", None),
    ("GET", "/api/ruggers/subnet/1", None),
    (
        "POST",
        "/api/ruggers/events",
        {
            "wallet": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
            "netuid": 1,
            "side": "buy",
            "amount_tao": 100.0,
        },
    ),
    ("POST", "/api/ruggers/scan", {"netuids": [1], "top_n": 1}),
    # Technical indicators (slice 7)
    ("GET", "/api/indicators", None),
    ("GET", "/api/indicators-convergence", None),
    ("GET", "/api/indicators/scheduler", None),
    # Learning loop write APIs (slice 6)
    (
        "POST",
        "/api/feedback",
        {
            "subnet_id": 1,
            "recommendation": "quant",
            "actual_performance": {"correct_prediction": True},
        },
    ),
    ("POST", "/api/learning/trigger", None),
    ("POST", "/api/predictions/resolver/run", None),
    # Scenario memory + pick history (slice 8)
    ("GET", "/api/scenario-memory", None),
    (
        "POST",
        "/api/scenario-memory",
        {"name": "contract-test", "features": {"avg_change_24h": 1.0}},
    ),
    ("GET", "/api/pick-history", None),
    # Oracle snapshot stub (slice 9)
    ("GET", "/api/oracle", None),
    # Pump analytics + price tracking (slice 10b)
    ("GET", "/api/pump-analytics", None),
    ("GET", "/api/price-tracking/baselines", None),
    ("GET", "/api/price-tracking/outcomes", None),
    # Rotation tracker (slice 10a)
    ("GET", "/api/rotation-tracker", None),
    # Freshness + weights (slice 11)
    ("GET", "/api/freshness", None),
    ("GET", "/api/council/weights", None),
    ("GET", "/api/weights", None),
    # SimiVision chat (slice 13)
    ("POST", "/api/simivision/chat", {"message": "contract-test ping"}),
    # Resolve + rotation tokens (slice 14a)
    ("GET", "/api/resolve-predictions", None),
    ("GET", "/api/rotation-tokens", None),
]


# Remaining routes from the historical FastAPI monolith, to be ported in later
# slices. Kept here as a visible checklist (NOT asserted yet).
NOT_YET_PORTED = [
    "/api/health",
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
