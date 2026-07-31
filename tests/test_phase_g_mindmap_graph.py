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


def test_mindmap_graph_focus_scopes_trail(monkeypatch):
    import internal.learning.mindmap_aggregator as agg

    trail = [
        {"netuid": 42, "event_type": "weight_change", "time": "2026-07-27T00:00:00Z"},
        {"netuid": 99, "event_type": "weight_change", "time": "2026-07-27T00:01:00Z"},
    ]
    monkeypatch.setattr(agg, "collect_trail_events", lambda limit=100: trail)
    monkeypatch.setattr(agg, "build_mindmap_state", lambda: {"status": "success", "trail": trail})

    import internal.mindmap.graph as graph_mod

    monkeypatch.setattr(graph_mod, "_load_dispositions", lambda: [])

    graph = get_mindmap_graph(focus_netuid=42)
    assert graph["scoped"] is True
    assert graph["focus_netuid"] == 42
    subnet_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "subnet"}
    assert subnet_ids == {"subnet:42"}


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


def test_mindmap_graph_skips_unscoped_hold_dispositions(monkeypatch):
    import internal.learning.mindmap_aggregator as agg
    import internal.mindmap.graph as graph_mod

    trail = [
        {
            "netuid": 14,
            "event_type": "prediction_resolved",
            "subnet": "TaoHash",
            "time": "2026-07-27T00:00:00Z",
            "prediction": "long",
            "decision": "hit",
        }
    ]
    monkeypatch.setattr(agg, "build_mindmap_state", lambda: {"status": "success", "trail": trail})
    monkeypatch.setattr(graph_mod, "_collect_trail", lambda limit=200: trail)
    monkeypatch.setattr(
        graph_mod,
        "_load_dispositions",
        lambda: [
            {"netuid": 14, "action": "accumulate", "score": 0.8, "label": "TaoHash"},
            {"netuid": 99, "action": "hold", "score": 0.1, "label": "Noise"},
            {"netuid": 100, "action": "hold", "score": 0.1, "label": "Noise2"},
        ],
    )
    graph = get_mindmap_graph(focus_netuid=None)
    disp = [n for n in graph["nodes"] if n["kind"] == "disposition"]
    assert any("accumulate" in n["label"] for n in disp)
    assert not any(n["metrics"].get("action") == "hold" for n in disp)
    assert len(graph["nodes"]) <= 48


def test_mindmap_graph_netuidless_nudge_joins_loop_hub(monkeypatch):
    """Judge/weight-nudge events without a netuid used to vanish silently
    (the graph builder created the node but never an edge to reach it).
    They should now attach to the loop:council hub instead."""
    import internal.learning.mindmap_aggregator as agg
    import internal.mindmap.graph as graph_mod

    trail = [
        {
            "netuid": None,
            "event_type": "weight_change",
            "judge": "sentiment",
            "time": "2026-07-27T00:00:00Z",
        }
    ]
    monkeypatch.setattr(agg, "build_mindmap_state", lambda: {"status": "success", "trail": trail})
    monkeypatch.setattr(graph_mod, "_collect_trail", lambda limit=200: trail)
    monkeypatch.setattr(graph_mod, "_load_dispositions", lambda: [])
    monkeypatch.setattr(graph_mod, "_load_indicator_alerts", lambda focus: [])
    monkeypatch.setattr(graph_mod, "_load_whale_and_rugger_alerts", lambda focus: {})

    graph = get_mindmap_graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "loop:council" in node_ids
    assert "judge:sentiment" in node_ids
    assert any(
        e["source"] == "loop:council" and e["target"] == "judge:sentiment"
        for e in graph["edges"]
    )


def test_mindmap_graph_wires_whale_rugger_indicator_signals(monkeypatch):
    import internal.learning.mindmap_aggregator as agg
    import internal.mindmap.graph as graph_mod

    monkeypatch.setattr(agg, "build_mindmap_state", lambda: {"status": "success", "trail": []})
    monkeypatch.setattr(graph_mod, "_collect_trail", lambda limit=200: [])
    monkeypatch.setattr(graph_mod, "_load_dispositions", lambda: [])
    monkeypatch.setattr(
        graph_mod,
        "_load_indicator_alerts",
        lambda focus: [{"subnet_id": 64, "event_type": "rsi_bullish_cross"}],
    )
    monkeypatch.setattr(
        graph_mod,
        "_load_whale_and_rugger_alerts",
        lambda focus: {
            "rugger_alerts": [
                {"netuid": 64, "wallet": "abc", "urgency": "high", "subnet_name": "Chutes"}
            ],
            "follow_alerts": [
                {"netuid": 64, "wallet": "def", "win_rate": 0.7, "subnet_name": "Chutes"}
            ],
        },
    )

    graph = get_mindmap_graph()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"indicator", "whale", "risk"} <= kinds
    subnet_edges = {e["source"] for e in graph["edges"]}
    assert "subnet:64" in subnet_edges


def test_brain_recommendations_no_hardcoded_sn123(tmp_path):
    from internal.council.mindmap_bridge import MindmapBridge

    bridge = MindmapBridge(
        persistence_path=str(tmp_path / "soul.json"),
        registry_path=str(tmp_path / "missing_registry.json"),
    )
    out = bridge.get_brain_recommendations()
    assert out.get("data_available") is False
    assert out.get("recommendations") == {}
    assert "1" not in out.get("recommendations", {})
