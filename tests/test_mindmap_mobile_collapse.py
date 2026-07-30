"""PR9 — mind map mobile collapse."""

from __future__ import annotations

from pathlib import Path


def test_mindmap_mobile_toggle_present():
    html = Path("templates/partials/mindmap_graph.html").read_text(encoding="utf-8")
    assert "mindmap-graph-mobile-toggle" in html
    assert "max-width: 480px" in html


def test_mindmap_js_wires_mobile_toggle():
    js = Path("static/js/mindmap_graph.js").read_text(encoding="utf-8")
    assert "mindmap-graph-mobile-toggle" in js
    assert "is-expanded" in js
