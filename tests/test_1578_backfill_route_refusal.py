from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal.learning import expert_backfill, routes


def test_refused_backfill_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(
        expert_backfill,
        "backfill_expert_attribution",
        lambda dry_run: {"ok": False, "reason": "persist_refused", "updated": 0},
    )
    routes._learning_snapshot_cache["at"] = 123.0
    app = FastAPI()
    app.include_router(routes.learning_router)

    response = TestClient(app).post("/api/learning/backfill-expert-attribution?dry_run=false")

    assert response.status_code >= 500, response.text
    assert routes._learning_snapshot_cache["at"] == 123.0
