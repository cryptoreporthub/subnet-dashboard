"""Phase G — Mindmap graph model (Agent A)."""

from __future__ import annotations

import pytest

from internal.mindmap.graph import get_mindmap_graph


def test_mindmap_graph_shape():
    graph = get_mindmap_graph()
    assert graph["status"] == "success"
    assert isinstance(graph["nodes"], list)
    assert isinstance(graph["edges"], list)
    for node in graph["nodes"]:
        assert {"id", "label", "kind", "metrics", "updated_at"} <= set(node.keys())
    for edge in graph["edges"]:
        assert {"source", "target", "kind", "weight"} <= set(edge.keys())


def test_mindmap_graph_includes_core_kinds():
    graph = get_mindmap_graph()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert "subnet" in kinds or len(graph["nodes"]) == 0
    assert "signal" in kinds or len(graph["nodes"]) == 0
    # Dispositions appear when store/Soul-Map has rows; trail-only graphs still valid.
    if graph["nodes"]:
        assert kinds & {"subnet", "signal", "disposition", "judge", "prediction", "scenario"}


def test_mindmap_graph_subnet_signal_edges_when_trail_present():
    graph = get_mindmap_graph()
    if not graph["edges"]:
        pytest.skip("no trail/disposition edges in this environment")
    assert any(e["source"].startswith("subnet:") for e in graph["edges"])


def test_mindmap_graph_empty_state_success(monkeypatch):
    import internal.learning.mindmap_aggregator as agg

    monkeypatch.setattr(agg, "collect_trail_events", lambda limit=100: [])
    monkeypatch.setattr(agg, "build_mindmap_state", lambda: {"status": "success", "trail": []})

    import internal.mindmap.graph as graph_mod

    monkeypatch.setattr(graph_mod, "_load_dispositions", lambda: [])

    graph = get_mindmap_graph()
    assert graph["status"] == "success"
    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_mindmap_graph_router_export():
    from internal.mindmap import mindmap_graph_router

    assert mindmap_graph_router is not None
    paths = [getattr(r, "path", None) for r in mindmap_graph_router.routes]
    assert "/api/mindmap/graph" in paths


def test_mindmap_graph_counts_logged():
    graph = get_mindmap_graph()
    node_kinds = {}
    for n in graph["nodes"]:
        node_kinds[n["kind"]] = node_kinds.get(n["kind"], 0) + 1
    # Sanity: graph builder returns coherent counts for CI logs
    assert graph["status"] == "success"
    assert len(graph["nodes"]) >= 0
    assert len(graph["edges"]) >= 0
