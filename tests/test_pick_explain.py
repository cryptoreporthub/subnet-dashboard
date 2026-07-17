"""§32 — pick explain API."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_pick_explain_returns_ok():
    resp = client.get("/api/pick-explain/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("ok", "not_found")
    if body.get("status") == "ok":
        assert body.get("verdict") in (
            "published",
            "gated_candidate",
            "not_today_pick",
        )
        assert "blockers" in body


def test_explain_subnet_not_found():
    from internal.council.pick_explain import explain_subnet

    out = explain_subnet(99999, [])
    assert out["status"] == "not_found"
