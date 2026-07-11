"""Phase E — cockpit data layer contract tests (Agent A)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from internal.cockpit.sections import SECTION_IDS, get_cockpit_section, get_cockpit_sections


def test_get_cockpit_sections_returns_twelve_fixed_ids():
    payload = get_cockpit_sections()
    assert payload["status"] == "success"
    sections = payload["sections"]
    assert len(sections) == 12
    assert [row["id"] for row in sections] == list(SECTION_IDS)


def test_section_schema_shape():
    payload = get_cockpit_sections()
    for row in payload["sections"]:
        assert isinstance(row["id"], str)
        assert isinstance(row["title"], str)
        assert isinstance(row["summary"], str)
        assert len(row["summary"]) > 10
        assert isinstance(row["metrics"], dict)
        assert row["status"] in {"live", "empty", "unavailable"}
        assert isinstance(row["updated_at"], str)
        assert row["updated_at"].endswith("Z")


def test_per_section_getter():
    row = get_cockpit_section("pump_ladder")
    assert row["id"] == "pump_ladder"
    assert row["title"] == "Pump Ladder"
    assert row["status"] in {"live", "empty", "unavailable"}


def test_unknown_section_returns_unavailable():
    row = get_cockpit_section("not_a_real_section")
    assert row["status"] == "unavailable"
    assert "Unknown" in row["summary"]


@pytest.mark.parametrize("section_id", SECTION_IDS)
def test_each_section_survives_dependency_failure(section_id):
    """Monkeypatching a builder to raise must not 500 the aggregate payload."""
    import internal.cockpit.sections as mod

    original = mod._BUILDERS[section_id]

    def _boom():
        raise RuntimeError(f"simulated failure for {section_id}")

    with patch.dict(mod._BUILDERS, {section_id: _boom}):
        payload = get_cockpit_sections()
    assert payload["status"] == "success"
    assert len(payload["sections"]) == 12
    row = next(s for s in payload["sections"] if s["id"] == section_id)
    assert row["status"] == "unavailable"
    assert "unavailable" in row["summary"].lower() or "temporarily" in row["summary"].lower()


def test_cockpit_api_route():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from internal.cockpit.routes import cockpit_router

    app = FastAPI()
    app.include_router(cockpit_router)
    client = TestClient(app)
    resp = client.get("/api/cockpit/sections")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["sections"]) == 12
