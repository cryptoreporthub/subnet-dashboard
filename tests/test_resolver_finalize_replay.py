"""A resolution replayed after its save was dropped must not write a second trail or lineage row.

When a cycle is abandoned, its predictions save is skipped. The revived cycle then reloads
the row still pending and grades it again. Finalize runs twice for one resolution, so the
decision history and the learning trail must each record it once.
"""

from __future__ import annotations

import json

import pytest

import internal.council.pick_history as pick_history
import internal.council.resolver as resolver
import internal.council.weights as weights
import internal.trace.store as trace_store


PREDICTION_ID = "pred-finalize-replay-1"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    trace_path = tmp_path / "decision_trace.json"
    soul_path = tmp_path / "soul_map.json"
    monkeypatch.setattr(trace_store, "TRACE_STORE_PATH", str(trace_path))
    # Keep the SQLite backend off so the JSON store is the only sink under test.
    monkeypatch.setattr(trace_store, "_CANONICAL_TRACE_PATH", str(tmp_path / "not-canonical.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver, "on_prediction_resolved", lambda *_a, **_k: None)
    monkeypatch.setattr(pick_history, "finalize_from_prediction", lambda *_a, **_k: None)
    return trace_path, soul_path


def _pending_prediction() -> dict:
    return {
        "id": PREDICTION_ID,
        "netuid": 7,
        "name": "Replay Finalize",
        "expert": "alpha",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "horizon_type": "hour",
        "created_at": "2026-07-01T00:00:00Z",
        "status": "pending",
    }


def _finalize_once() -> None:
    resolver.atomic_finalize_resolution(
        _pending_prediction(),
        actual_pct=10.0,
        outcome="hit",
        correct=True,
        resolved_price=110.0,
        resolved_at="2026-07-01T01:00:00Z",
    )


def _lineage_rows(trace_path) -> list:
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    return [
        r
        for r in data.get("records", [])
        if r.get("decision_type") == "prediction_resolve"
        and isinstance(r.get("decision"), dict)
        and r["decision"].get("prediction_id") == PREDICTION_ID
    ]


def _trail_rows(soul_path) -> list:
    data = json.loads(soul_path.read_text(encoding="utf-8"))
    trail = (data.get("soul_map_state") or {}).get("learning_trail") or []
    return [
        e
        for e in trail
        if e.get("event_type") == "prediction_resolved"
        and isinstance(e.get("evidence"), dict)
        and e["evidence"].get("prediction_id") == PREDICTION_ID
    ]


def test_replayed_finalize_records_one_lineage_row(isolated):
    trace_path, _soul_path = isolated
    _finalize_once()
    _finalize_once()

    assert len(_lineage_rows(trace_path)) == 1


def test_replayed_finalize_records_one_trail_row(isolated):
    _trace_path, soul_path = isolated
    _finalize_once()
    _finalize_once()

    assert len(_trail_rows(soul_path)) == 1


def test_legacy_trace_row_with_non_dict_decision_does_not_block_lineage(isolated):
    trace_path, _soul_path = isolated
    trace_path.write_text(
        json.dumps(
            {
                "meta": {},
                "records": [{"decision_type": "prediction_resolve", "decision": "legacy-string"}],
            }
        ),
        encoding="utf-8",
    )

    _finalize_once()

    assert len(_lineage_rows(trace_path)) == 1


def test_legacy_trail_row_with_non_dict_evidence_does_not_block_trail(isolated):
    _trace_path, soul_path = isolated
    soul_path.write_text(
        json.dumps(
            {
                "soul_map_state": {
                    "learning_trail": [{"event_type": "prediction_resolved", "evidence": "legacy-string"}]
                }
            }
        ),
        encoding="utf-8",
    )

    _finalize_once()

    assert len(_trail_rows(soul_path)) == 1


def test_replayed_finalize_after_trail_compaction_records_no_second_trail_row(isolated):
    """The trail keeps only its newest 200 rows, so the first row can be compacted away before a replay."""
    from internal.council.mindmap_bridge import MindmapBridge

    _trace_path, soul_path = isolated
    _finalize_once()
    bridge = MindmapBridge(persistence_path=str(soul_path))
    for i in range(200):
        bridge.append_learning_trail({"event_type": "rotation_tokens_update", "evidence": {"seq": i}})
    assert _trail_rows(soul_path) == []

    _finalize_once()

    assert _trail_rows(soul_path) == []


def test_concurrent_bridges_keep_both_resolved_ids_and_trail_rows(tmp_path, monkeypatch):
    """Two bridges loaded from one file must not erase each other's appends.

    The cache TTL is zeroed so every write reads the file as another process would see it.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    monkeypatch.setattr(soul_map_io, "_CACHE_TTL", 0)
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    first = MindmapBridge(persistence_path=str(soul_path))
    second = MindmapBridge(persistence_path=str(soul_path))

    first.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-a"}},
        resolved_prediction_id="p-a",
    )
    second.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-b"}},
        resolved_prediction_id="p-b",
    )

    state = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert set(state["resolved_prediction_ids"]) == {"p-a", "p-b"}
    assert {e["evidence"]["prediction_id"] for e in state["learning_trail"]} == {"p-a", "p-b"}


def test_stale_bridge_save_keeps_resolved_id_recorded_by_another_bridge(tmp_path, monkeypatch):
    """A bridge loaded before another bridge's resolution must not drop that id on its next save.

    The stale bridge only knows its own snapshot, so its whole-state save must union the
    persisted ledger rather than overwrite it.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    monkeypatch.setattr(soul_map_io, "_CACHE_TTL", 0)
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    stale = MindmapBridge(persistence_path=str(soul_path))
    resolver_bridge = MindmapBridge(persistence_path=str(soul_path))

    resolver_bridge.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-a"}},
        resolved_prediction_id="p-a",
    )
    stale.update_soul_map({"decisions": []})

    state = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert "p-a" in state["resolved_prediction_ids"]
