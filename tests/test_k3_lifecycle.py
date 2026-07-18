"""K3-3 — story path promoted into dossier lifecycle layers."""

from fastapi.testclient import TestClient

from server import app


def test_home_renders_k3_lifecycle_layers():
    with TestClient(app) as client:
        html = client.get("/").text
    assert "k3-lifecycle-outcome" in html
    assert "k3-lifecycle-learning" in html
    assert "Council lifecycle" in html


def test_mindmap_story_path_returns_steps():
    with TestClient(app) as client:
        resp = client.get("/api/mindmap/story-path")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "success"
    assert "steps" in body
