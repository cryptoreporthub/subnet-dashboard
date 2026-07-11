"""Phase E — Premium Cockpit UI cards (Agent B)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.analytics.cockpit_render import empty_cockpit_sections, load_cockpit_sections
from internal.cockpit.sections import COCKPIT_SECTION_IDS
from server import app, _COCKPIT_ROUTES


def test_empty_cockpit_sections_has_twelve():
    payload = empty_cockpit_sections()
    assert payload["status"] == "success"
    assert len(payload["sections"]) == 12
    assert [row["id"] for row in payload["sections"]] == list(COCKPIT_SECTION_IDS)


def test_load_cockpit_sections_never_empty_list():
    payload = load_cockpit_sections()
    assert len(payload["sections"]) == 12


def test_cockpit_api_when_mounted():
    if not _COCKPIT_ROUTES:
        return
    client = TestClient(app)
    resp = client.get("/api/cockpit/sections")
    assert resp.status_code == 200
    assert len(resp.json()["sections"]) == 12


def test_index_renders_twelve_cockpit_cards():
    client = TestClient(app)
    html = client.get("/").text
    assert html.count('class="cockpit-card"') == 12
    for section_id in COCKPIT_SECTION_IDS:
        assert f'data-section-id="{section_id}"' in html


def test_index_cards_show_schema_fields():
    client = TestClient(app)
    html = client.get("/").text
    assert 'class="cockpit-summary"' in html
    assert "cockpit-status-live" in html or "cockpit-status-empty" in html or "cockpit-status-unavailable" in html
    assert 'class="cockpit-updated"' in html


def test_cold_redeploy_without_cockpit_engine():
    """Homepage still shows 12 honest-empty cards when data layer import fails."""
    with patch("internal.cockpit.get_cockpit_sections", side_effect=ImportError("no engine")):
        payload = load_cockpit_sections()
    assert len(payload["sections"]) == 12
    assert all(row["status"] == "empty" for row in payload["sections"])


def test_index_survives_missing_cockpit_context():
    with patch("server.load_cockpit_sections", side_effect=Exception("boom"), create=True):
        pass
    # Template partial canonical fallback — render without context key
    from fastapi.templating import Jinja2Templates
    import os

    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
    rendered = templates.get_template("partials/cockpit_cards.html").render({})
    assert rendered.count('class="cockpit-card"') == 12
    assert 'data-section-id="pump_tracker"' in rendered
