"""Phase G — interactive Mindmap trail UI (redesigned from node-link graph to a
subnet-grouped receipts list; see cursor-agents-communication for rationale)."""

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
        {"source": "subnet:1", "target": "signal:pick", "kind": "hour_pick", "weight": 0.8},
    ],
}

EMPTY_GRAPH = {"status": "success", "nodes": [], "edges": []}


def test_mindmap_partial_container_markup():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render({})
    assert 'id="mindmap-graph-root"' in html
    assert 'id="mindmap-trail-list"' in html
    assert 'id="mindmap-spine-chrome"' in html
    assert 'aria-live="polite"' in html
    assert "/static/js/mindmap_graph.js" in html
    # Full replace: no SVG node-link graph and no separate detail panel.
    assert 'id="mindmap-graph-svg"' not in html
    assert 'id="mindmap-detail-panel"' not in html


def test_mindmap_partial_spine_chrome_between_status_and_trail():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render({})
    status_pos = html.index('id="mindmap-integration-status"')
    chrome_pos = html.index('id="mindmap-spine-chrome"')
    trail_pos = html.index('id="mindmap-trail-list"')
    assert status_pos < chrome_pos < trail_pos
    assert 'data-spine="conviction"' in html
    assert 'data-spine="learn"' in html


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


def test_index_includes_mindmap_section():
    import server as srv

    srv._prime_emergency_home_html()
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="mindmap-graph-section"' in html
    assert 'id="mindmap-trail-list"' in html
    assert 'id="mindmap-spine-chrome"' in html
    assert "Interactive Mindmap" in html


def test_mindmap_js_asset_served():
    client = TestClient(app)
    resp = client.get("/static/js/mindmap_graph.js")
    assert resp.status_code == 200
    assert "renderTrail" in resp.text
    assert "buildTrailGroups" in resp.text


def test_mindmap_js_covers_loop_hub_and_market_signals():
    """Every nudge/signal, not just subnet-scoped trail rows: the loop hub
    (netuid-less weight nudges) and whale/rugger/indicator kinds must be
    recognized by the Trail renderer, not just the backend graph."""
    client = TestClient(app)
    resp = client.get("/static/js/mindmap_graph.js")
    src = resp.text
    assert "isLoop" in src
    assert "data-loop" in src
    assert "GRAPH_FETCH_TIMEOUT_MS = 12000" in src
    for kind in ("loop", "whale", "risk", "indicator"):
        assert f"{kind}:" in src


def test_mindmap_js_honest_timeout_and_empty_states():
    client = TestClient(app)
    src = client.get("/static/js/mindmap_graph.js").text
    assert "emptyMessageForGraph" in src
    assert "isUsableInitialGraph" in src
    assert "Graph build timed out" in src
    assert "Graph build failed" in src
    assert "cached" in src or "Graph build timed out" in src
    assert "panel will activate when /api/mindmap/graph is wired" not in src


def test_mindmap_js_focus_spine_sort_and_consume_initial_graph():
    """Task 2b: focus group sorts after loop, data-focus=1, SSR graph consumed once."""
    client = TestClient(app)
    src = client.get("/static/js/mindmap_graph.js").text
    assert "data-focus" in src
    assert "getFocusNetuid" in src
    assert "delete root.dataset.initialGraph" in src
    assert "renderSpineChrome" in src
    assert "home:hydrate-cache" in src
    assert "home:hydrate-trail" in src


def test_mindmap_partial_prefers_reduced_motion():
    html = TEMPLATES.get_template("partials/mindmap_graph.html").render({})
    assert "prefers-reduced-motion" in html


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
