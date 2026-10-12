"""Security tests for judge postmortem path handling (#1367)."""

import json
import os
import pytest
from fastapi.testclient import TestClient

from server import app
from internal.judges.postmortems import (
    POSTMORTEMS_DIR,
    UnknownJudgeError,
    _path,
    canonical_judge_name,
    list_for_judge,
    record,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def planted_outside_list(tmp_path, monkeypatch):
    """List-shaped JSON outside POSTMORTEMS_DIR that traversal must not read."""
    data_dir = tmp_path / "data"
    postmortems_dir = data_dir / "postmortems"
    postmortems_dir.mkdir(parents=True)
    probe = data_dir / "probe.json"
    probe.write_text(json.dumps([{"secret": "outside-dir"}]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "internal.judges.postmortems.POSTMORTEMS_DIR",
        os.path.join("data", "postmortems"),
    )
    return probe


def test_path_rejects_traversal():
    with pytest.raises(UnknownJudgeError):
        _path("../probe")


def test_canonical_judge_case_insensitive():
    assert canonical_judge_name("ORACLE") == "oracle"
    assert canonical_judge_name("Echo") == "echo"


def test_record_rejects_traversal_and_does_not_write(planted_outside_list, tmp_path):
    with pytest.raises(UnknownJudgeError):
        record("../probe", {"id": 1, "direction": "up", "predicted_pct": 1.0}, -1.0)
    postmortems_dir = tmp_path / "data" / "postmortems"
    if postmortems_dir.exists():
        assert list(postmortems_dir.glob("*.json")) == []
    assert planted_outside_list.read_text() == json.dumps([{"secret": "outside-dir"}])


def test_list_for_judge_valid_oracle(planted_outside_list):
    oracle_file = os.path.join(POSTMORTEMS_DIR, "oracle.json")
    os.makedirs(os.path.dirname(oracle_file), exist_ok=True)
    with open(oracle_file, "w", encoding="utf-8") as f:
        json.dump([{"judge": "oracle", "prediction_id": 9}], f)
    rows = list_for_judge("ORACLE")
    assert rows == [{"judge": "oracle", "prediction_id": 9}]


@pytest.mark.parametrize(
    "judge_value",
    ["../probe", "..\\probe", "%2e%2e/probe", "/etc/passwd", "not-a-judge"],
)
def test_api_postmortems_query_rejects_unsafe(client, planted_outside_list, judge_value):
    resp = client.get("/api/postmortems", params={"judge": judge_value})
    assert resp.status_code in (400, 404)
    body = resp.json()
    assert "outside-dir" not in json.dumps(body)
    assert "secret" not in json.dumps(body)
    detail = body.get("detail", "")
    if isinstance(detail, str):
        assert "data/" not in detail
        assert "probe" not in detail.lower()


@pytest.mark.parametrize(
    "path_suffix",
    ["../probe", "not-a-judge"],
)
def test_api_postmortems_by_judge_rejects_unsafe(client, planted_outside_list, path_suffix):
    resp = client.get(f"/api/postmortems/{path_suffix}")
    assert resp.status_code in (400, 404, 422)
    if resp.status_code == 422:
        return
    assert "outside-dir" not in resp.text


def test_api_judges_postmortems_unknown_judge_404(client):
    resp = client.get("/api/judges/not-a-judge/postmortems")
    assert resp.status_code == 404
    assert resp.json().get("detail") == "unknown judge"


def test_symlink_escape_blocked(tmp_path, monkeypatch):
    from internal.judges.postmortems import UnsafeJudgePathError

    data_dir = tmp_path / "data"
    postmortems_dir = data_dir / "postmortems"
    postmortems_dir.mkdir(parents=True)
    outside = data_dir / "outside.json"
    outside.write_text(json.dumps([{"leaked": True}]), encoding="utf-8")
    link = postmortems_dir / "oracle.json"
    link.symlink_to(outside)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "internal.judges.postmortems.POSTMORTEMS_DIR",
        os.path.join("data", "postmortems"),
    )
    with pytest.raises(UnsafeJudgePathError):
        list_for_judge("oracle")
