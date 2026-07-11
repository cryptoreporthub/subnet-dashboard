"""Phase G — interactive Mindmap graph UI (Agent B)."""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from server import app


TEMPLATES = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

FAKE_GRAPH = {
    "status": "success",
    "nodes": [
        {
            "id": "subnet:1",
            "label": "Alpha",
            "kind": "subnet",
            "metrics": {"netuid": 1, "action": "accumulate"},
            "updated_at": "2026-07-11T00:00:00Z",
        },
        {
            "id": "signal:pick",
            "label": "Hour Pick",
            "kind": "signal",
            "metrics": {"confidence": 0.82},
            "updated_at": "2026-07-11T00:05:00Z",
        },
    ],
    "edges": [
        {"source": "signal:pick", "target": "subnet:1", "kind": "influences", "weight": 0.8},
    ],
}

EMPTY_GRAPH = {"status": "success", "nodes": [], "edges": []}


def test_mindmap_partial_container_and_detail_panel_markup():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render({})
    assert 'id="mindmap-graph-root"' in html
    assert 'id="mindmap-graph-svg"' in html
    assert 'id="mindmap-detail-panel"' in html
    assert 'id="mindmap-detail-metrics"' in html
    assert "/static/js/mindmap_graph.js" in html


def test_mindmap_partial_renders_with_fake_graph_payload():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render(
        {"mindmap_graph": FAKE_GRAPH}
    )
    assert "data-initial-graph" in html
    assert "subnet:1" in html
    assert 'id="mindmap-graph-empty"' in html


def test_mindmap_partial_empty_graph_honest_empty_state():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render(
        {"mindmap_graph": EMPTY_GRAPH}
    )
    assert 'id="mindmap-graph-empty"' in html
    assert "empty" in html.lower()
    assert 'id="mindmap-detail-panel"' in html


def test_index_includes_mindmap_section():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="mindmap-graph-section"' in html
    assert 'id="mindmap-detail-panel"' in html
    assert "Interactive Mindmap" in html


def test_mindmap_js_asset_served():
    client = TestClient(app)
    resp = client.get("/static/js/mindmap_graph.js")
    assert resp.status_code == 200
    assert "renderGraph" in resp.text or "mindmap-graph-root" in resp.text


def test_initial_graph_json_embedded_is_valid():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render(
        {"mindmap_graph": FAKE_GRAPH}
    )
    marker = "data-initial-graph='"
    start = html.index(marker) + len(marker)
    end = html.index("'", start)
    payload = json.loads(html[start:end])
    assert payload["status"] == "success"
    assert len(payload["nodes"]) == 2
