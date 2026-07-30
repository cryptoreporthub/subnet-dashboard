"""Dev Pulse v1 — registry github + graded snippets."""

from internal.dev_radar.service import build_dev_radar_payload, build_dev_radar_rows


def test_dev_radar_rows_risk_flag_and_snippet(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    subnets = [
        {"netuid": 1, "name": "Alpha", "github": "https://github.com/org/alpha", "emission": 2.0},
        {"netuid": 2, "name": "Beta", "github": "", "emission": 3.0},
    ]
    rows = build_dev_radar_rows(subnets, limit=10)
    by_id = {r["netuid"]: r for r in rows}
    assert by_id[1]["has_public_repo"] is True
    assert by_id[1]["risk_flag"] is None
    assert by_id[1]["graded_snippet"]
    assert by_id[2]["risk_flag"] == "no_public_repo"
    assert by_id[2]["has_public_repo"] is False


def test_dev_radar_sort_repos_first_by_emission(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    subnets = [
        {"netuid": 1, "name": "Low", "github": "https://github.com/a/b", "emission": 1.0},
        {"netuid": 2, "name": "HighNoRepo", "emission": 9.0},
        {"netuid": 3, "name": "HighRepo", "github": "https://github.com/a/c", "emission": 8.0},
    ]
    rows = build_dev_radar_rows(subnets, limit=10)
    assert [r["netuid"] for r in rows] == [3, 1, 2]


def test_dev_radar_payload_honest_empty(monkeypatch):
    monkeypatch.setattr("internal.dev_radar.service._load_registry_subnets", lambda: [])
    payload = build_dev_radar_payload(limit=12)
    assert payload["status"] == "success"
    assert payload["data_available"] is False
    assert payload["subnets"] == []
    assert "warming up" in (payload.get("message") or "").lower()


def test_dev_radar_api_contract():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as test_client:
        resp = test_client.get("/api/dev-radar?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "success"
    assert "subnets" in body
    assert "summary" in body
    assert len(body["subnets"]) <= 5
