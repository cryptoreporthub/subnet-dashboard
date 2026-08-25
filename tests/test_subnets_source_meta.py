"""§27-2 — /api/subnets source meta."""
from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_subnets_meta_includes_source():
    """Live /api/subnets must expose source meta and a non-empty universe.

    Env: meta.total>0 needs config/registry.json or a persisted universe snapshot
    (both absent in a fresh Cloud Agent checkout). See docs/pr-1041-env-setup-failures.md.
    """
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
