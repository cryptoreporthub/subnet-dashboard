"""Security tests for postmortem path handling (issue #1367)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from internal.judges import postmortems
from server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def probe_outside_postmortems_dir(tmp_path, monkeypatch):
    """Plant a list-shaped JSON file outside data/postmortems/."""
    data_dir = tmp_path / "data"
    postmortems_dir = data_dir / "postmortems"
    postmortems_dir.mkdir(parents=True)
    probe_path = data_dir / "probe.json"
    probe_path.write_text(json.dumps([{"secret": "outside-dir"}]), encoding="utf-8")
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))
    return probe_path


def test_path_rejects_traversal():
    with pytest.raises(ValueError, match="Unknown judge"):
        postmortems._path("../probe")


def test_record_rejects_traversal_and_does_not_write(tmp_path, monkeypatch):
    postmortems_dir = tmp_path / "postmortems"
    postmortems_dir.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))
    prediction = {"id": "x", "netuid": 1, "direction": "up", "predicted_pct": 1.0}
    with pytest.raises(ValueError, match="Unknown judge"):
        postmortems.record("../x", prediction, actual_pct=-1.0)
    assert list(postmortems_dir.glob("*.json")) == []


def test_path_valid_judges(tmp_path, monkeypatch):
    postmortems_dir = tmp_path / "postmortems"
    postmortems_dir.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))
    for name in ("oracle", "ECHO", "Pulse"):
        path = postmortems._path(name)
        assert path.endswith(f"{name.lower()}.json")
        assert os.path.realpath(path).startswith(os.path.realpath(str(postmortems_dir)))


@pytest.mark.parametrize(
    "judge_param",
    ["../probe", "..\\probe", "%2e%2e/probe", "/etc/passwd"],
)
def test_api_postmortems_query_rejects_traversal(client, probe_outside_postmortems_dir, judge_param):
    response = client.get("/api/postmortems", params={"judge": judge_param})
    assert response.status_code == 404
    body = response.json()
    assert "secret" not in json.dumps(body)
    assert judge_param not in json.dumps(body)


@pytest.mark.parametrize("route", ["/api/postmortems/not-a-judge", "/api/judges/not-a-judge/postmortems"])
def test_unknown_judge_rejected(client, route):
    response = client.get(route)
    assert response.status_code == 404
    assert response.json().get("detail") == "Unknown judge"


def test_unknown_judge_query_param(client):
    response = client.get("/api/postmortems", params={"judge": "not-a-judge"})
    assert response.status_code == 404
    assert response.json().get("detail") == "Unknown judge"


def test_symlink_judge_json_outside_dir_not_leaked_via_api(tmp_path, monkeypatch, client):
    """Registered judge file symlinked outside POSTMORTEMS_DIR must not expose data."""
    data_dir = tmp_path / "data"
    postmortems_dir = data_dir / "postmortems"
    postmortems_dir.mkdir(parents=True)
    outside = data_dir / "outside.json"
    outside.write_text(json.dumps([{"secret": "symlink-leak"}]), encoding="utf-8")
    (postmortems_dir / "oracle.json").symlink_to(outside)
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))

    with pytest.raises(ValueError, match="outside postmortems"):
        postmortems.list_for_judge("oracle")

    for route in (
        "/api/postmortems/oracle",
        "/api/postmortems?judge=oracle",
        "/api/judges/oracle/postmortems",
    ):
        response = client.get(route)
        assert response.status_code == 404
        assert "secret" not in response.text
        assert "symlink-leak" not in response.text

    aggregate = client.get("/api/postmortems")
    assert aggregate.status_code == 200
    body = aggregate.json()
    assert body["postmortems"]["oracle"] == []
    assert "symlink-leak" not in aggregate.text
    assert "secret" not in aggregate.text


def test_save_refuses_tmp_symlink(tmp_path, monkeypatch):
    postmortems_dir = tmp_path / "postmortems"
    postmortems_dir.mkdir()
    outside = tmp_path / "escaped.json"
    outside.write_text("[]", encoding="utf-8")
    (postmortems_dir / "oracle.json.tmp").symlink_to(outside)
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(postmortems_dir))
    with pytest.raises(OSError, match="symlink"):
        postmortems._save("oracle", [{"judge": "oracle"}])
    assert outside.read_text(encoding="utf-8") == "[]"


def test_valid_judges_all_routes(client):
    for name in ("oracle", "ECHO", "pulse"):
        canon = name.lower()
        r1 = client.get(f"/api/postmortems/{name}")
        assert r1.status_code == 200
        assert r1.json()["judge"] == canon

        r2 = client.get("/api/postmortems", params={"judge": name})
        assert r2.status_code == 200
        assert r2.json()["judge"] == canon

        r3 = client.get(f"/api/judges/{name}/postmortems")
        assert r3.status_code == 200
        assert r3.json()["judge"] == canon
