"""Phase E — Premium Cockpit UI (Agent B): templates + server wiring."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from internal.cockpit.sections import COCKPIT_SECTION_IDS
from server import app, _COCKPIT_ROUTES


def test_cockpit_api_when_mounted():
    if not _COCKPIT_ROUTES:
        return
    client = TestClient(app)
    resp = client.get("/api/cockpit/sections")
    assert resp.status_code == 200
    assert len(resp.json()["sections"]) == 12


def test_index_renders_twelve_cockpit_cards_from_sections():
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


def test_cold_redeploy_template_fallback_without_context():
    from fastapi.templating import Jinja2Templates
    import os

    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
    rendered = templates.get_template("partials/cockpit_cards.html").render({})
    assert rendered.count('class="cockpit-card"') == 12
    assert 'data-section-id="pump_tracker"' in rendered
    assert 'class="cockpit-summary"' in rendered


def test_cold_redeploy_when_sections_short():
    from fastapi.templating import Jinja2Templates
    import os

    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
    rendered = templates.get_template("partials/cockpit_cards.html").render(
        {
            "cockpit_sections": {
                "status": "success",
                "sections": [
                    {
                        "id": "pump_ladder",
                        "title": "Pump Ladder",
                        "summary": "One live row only.",
                        "metrics": {"tracked_subnets": 3},
                        "status": "live",
                        "updated_at": "2026-07-11T00:00:00Z",
                    }
                ],
            }
        }
    )
    assert rendered.count('class="cockpit-card"') == 12
    assert "One live row only." in rendered


def test_index_without_cockpit_sections_still_renders_twelve():
    with patch("server.get_cockpit_sections", side_effect=ImportError("no cockpit"), create=True):
        with patch(
            "internal.cockpit.get_cockpit_sections",
            side_effect=ImportError("no cockpit"),
        ):
            # Patch the import inside index handler path
            pass
    client = TestClient(app)
    with patch(
        "internal.cockpit.get_cockpit_sections",
        side_effect=ImportError("no cockpit"),
    ):
        # server imports get_cockpit_sections inside index(); patch at source module
        html = client.get("/").text
    assert html.count('class="cockpit-card"') == 12
