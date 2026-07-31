"""Mindmap — grouped trail is a plain list, so there is no separate mobile
mode to test: one markup path renders correctly at every width. This
replaces the old "collapse behind a toggle" test for the removed SVG graph
(see cursor-agents-communication for rationale on the full replace)."""

from __future__ import annotations

from pathlib import Path


def test_mindmap_has_no_mobile_toggle_hack():
    html = Path("templates/partials/mindmap_graph.html").read_text(encoding="utf-8")
    # The Trail list needs no expand-behind-a-button workaround — it's just a
    # scrolling <details> list, so the old toggle/collapse hack must be gone.
    assert "mindmap-graph-mobile-toggle" not in html
    assert "is-expanded" not in html


def test_mindmap_trail_group_touch_target():
    html = Path("templates/partials/mindmap_graph.html").read_text(encoding="utf-8")
    assert "mindmap-trail-group__summary" in html
    assert "min-height: 48px" in html


def test_mindmap_js_has_no_toggle_wiring():
    js = Path("static/js/mindmap_graph.js").read_text(encoding="utf-8")
    assert "mindmap-graph-mobile-toggle" not in js
    assert "is-expanded" not in js
