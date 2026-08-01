"""Mindmap graph UI — integration_status legend (PR M3)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from internal.learning.mindmap_aggregator import _build_integration_status
from server import app

TEMPLATES = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

_GRAPH_WITH_STATUS = {
    "status": "success",
    "nodes": [],
    "edges": [],
    "integration_status": _build_integration_status(),
}


def test_mindmap_partial_renders_integration_status_legend():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render(
        {"mindmap_graph": _GRAPH_WITH_STATUS}
    )
    assert 'id="mindmap-integration-status"' in html
    assert 'data-source="council_trail"' in html
    assert "Council Trail" in html
    assert 'mindmap-integration-badge--closed' in html
    assert 'data-source="judges"' in html
    assert 'title="Not yet wired — pending activation"' in html


def test_index_includes_integration_status_legend():
    import server as srv

    srv._prime_emergency_home_html()
    srv._warm_homepage_cache(None)
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="mindmap-integration-status"' in html
    assert "Council Trail" in html
    assert "Whales &amp; Indicators" in html or "Whales & Indicators" in html


def test_mindmap_js_updates_integration_status_legend():
    client = TestClient(app)
    src = client.get("/static/js/mindmap_graph.js").text
    assert "renderIntegrationStatusLegend" in src
    assert "isValidIntegrationStatus" in src
    assert "council_trail" in src
