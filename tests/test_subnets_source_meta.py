"""§27-2 — /api/subnets source meta."""
from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_subnets_meta_includes_source():
    resp = client.get("/api/subnets?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    meta = data.get("meta") or {}
    assert "source" in meta
    assert "sources" in meta
    assert isinstance(meta["sources"], list)
    assert meta.get("total", 0) > 0
    subs = data.get("subnets") or []
    if subs:
        assert "source" in subs[0]
        assert "sources" in subs[0]
