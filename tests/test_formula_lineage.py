"""Formula lineage API — cited sources + learning-loop state."""

import pytest
from fastapi.testclient import TestClient

from internal.council.formula_lineage import build_all_lineage, build_lane_lineage
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_build_lane_lineage_dark_horse():
    lane = build_lane_lineage("dark_horse")
    assert lane is not None
    assert lane["id"] == "dark_horse"
    assert "Martin" in lane["inspiration"][0]["citation"]
    assert lane["current_formula"]["expression"]
    assert "learning_loop" in lane
    assert lane["learning_loop"].get("feeds")


def test_build_all_lineage_catalog():
    catalog = build_all_lineage()
    assert catalog["status"] == "ok"
    ids = {lane["id"] for lane in catalog["lanes"]}
    assert "dark_horse" in ids
    assert "oracle" in ids


def test_api_formula_lineage_routes(client):
    resp = client.get("/api/formula-lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert len(body.get("lanes") or []) >= 7

    resp2 = client.get("/api/formula-lineage/dark_horse")
    assert resp2.status_code == 200
    assert resp2.json()["lane"]["id"] == "dark_horse"

    assert client.get("/api/formula-lineage/not_a_lane").status_code == 404
