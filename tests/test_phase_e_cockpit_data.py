"""Phase E — Premium Cockpit section data layer (get_cockpit_sections)."""

from __future__ import annotations

import pytest

from internal.cockpit.sections import COCKPIT_SECTION_IDS, get_cockpit_section, get_cockpit_sections


REQUIRED_KEYS = {"id", "title", "summary", "metrics", "status", "updated_at"}
VALID_STATUSES = {"live", "empty", "unavailable"}


def test_get_cockpit_sections_returns_twelve_fixed_ids():
    payload = get_cockpit_sections()
    assert payload["status"] == "success"
    sections = payload["sections"]
    assert len(sections) == 12
    assert [s["id"] for s in sections] == list(COCKPIT_SECTION_IDS)


def test_cockpit_section_schema_shape():
    payload = get_cockpit_sections()
    for section in payload["sections"]:
        assert REQUIRED_KEYS <= set(section.keys())
        assert section["status"] in VALID_STATUSES
        assert isinstance(section["summary"], str)
        assert section["summary"]
        assert isinstance(section["metrics"], dict)
        assert section["updated_at"].endswith("Z")


def test_get_cockpit_section_single():
    section = get_cockpit_section("pump_ladder")
    assert section["id"] == "pump_ladder"
    assert section["title"] == "Pump Ladder"
    assert section["status"] in VALID_STATUSES


def test_unknown_section_id_raises():
    with pytest.raises(KeyError):
        get_cockpit_section("not_a_real_panel")


@pytest.mark.parametrize("section_id", COCKPIT_SECTION_IDS)
def test_section_survives_dependency_failure(section_id, monkeypatch):
    import internal.cockpit.sections as mod

    builder = mod._SECTION_BUILDERS[section_id]

    def _boom():
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setitem(mod._SECTION_BUILDERS, section_id, _boom)
    section = get_cockpit_section(section_id)
    assert section["id"] == section_id
    assert section["status"] == "unavailable"
    assert "unavailable" in section["summary"].lower() or "temporarily" in section["summary"].lower()
    assert section["metrics"] == {}

    # Full payload still returns 12 sections without raising
    payload = get_cockpit_sections()
    assert len(payload["sections"]) == 12
    monkeypatch.setitem(mod._SECTION_BUILDERS, section_id, builder)


def test_cockpit_router_exports():
    from internal.cockpit import cockpit_router

    assert cockpit_router is not None
    paths = [getattr(r, "path", None) for r in cockpit_router.routes]
    assert "/api/cockpit/sections" in paths
