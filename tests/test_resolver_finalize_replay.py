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
    assert {e["evidence"]["prediction_id"] for e in state["learning_trail"]} == {"p-a"}


def test_append_after_external_write_within_cache_ttl_keeps_external_trail_row(tmp_path, monkeypatch):
    """Another process writes the file inside this process's cache TTL. Our append must keep its row.

    The bridge primes the cache when it loads. The external row exists only on disk, so a writer
    that starts from the cached blob would replace the file and drop it.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    monkeypatch.setattr(soul_map_io, "_CACHE_TTL", 60)
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))

    soul_path.write_text(
        json.dumps(
            {"soul_map_state": {"learning_trail": [{"event_type": "external", "evidence": {}}]}}
        ),
        encoding="utf-8",
    )
    bridge.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-own"}},
        resolved_prediction_id="p-own",
    )

    state = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert {e["event_type"] for e in state["learning_trail"]} == {"external", "prediction_resolved"}
    assert "p-own" in state["resolved_prediction_ids"]


def test_failed_save_keeps_selector_output_in_bridge_memory(tmp_path, monkeypatch):
    """A save that fails on disk must not roll back the bridge's in-memory state.

    A long-lived bridge keeps running after a failed write, so its in-memory copy is the only
    copy of the pending update.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))
    selector_output = {"decisions": [{"subnet_id": 7, "recommended_action": "hold"}]}

    def _fail_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(soul_map_io.os, "replace", _fail_replace)
    bridge.update_soul_map(selector_output)

    assert bridge.soul_map_state["last_selector_output"] == selector_output


def test_failed_append_keeps_trail_row_and_ledger_in_bridge_memory(tmp_path, monkeypatch):
    """A trail append whose disk write fails must keep its row in the bridge's memory.

    Copying the write result back would restore the pre-append snapshot and drop the row.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))
    entry = {"event_type": "prediction_resolved", "evidence": {"seq": 1}}

    def _fail_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(soul_map_io.os, "replace", _fail_replace)
    bridge.append_learning_trail(entry, resolved_prediction_id="p-failed")

    assert entry in bridge.soul_map_state["learning_trail"]
    assert "p-failed" in bridge.soul_map_state["resolved_prediction_ids"]


def test_successful_append_shows_other_bridges_rows_in_bridge_memory(tmp_path, monkeypatch):
    """A successful append must leave the bridge holding every row now on disk, not just its own.

    The other bridge's append lands after this bridge loaded, so this bridge's snapshot is stale.
    """
    import internal.store.soul_map_io as soul_map_io
    from internal.council.mindmap_bridge import MindmapBridge

    monkeypatch.setattr(soul_map_io, "_CACHE_TTL", 0)
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    stale = MindmapBridge(persistence_path=str(soul_path))
    other = MindmapBridge(persistence_path=str(soul_path))

    other.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-other"}},
        resolved_prediction_id="p-other",
    )
    stale.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-own"}},
        resolved_prediction_id="p-own",
    )

    memory = stale.soul_map_state
    assert {e["evidence"]["prediction_id"] for e in memory["learning_trail"]} == {"p-other", "p-own"}
    assert set(memory["resolved_prediction_ids"]) == {"p-other", "p-own"}


def _fail_first_replace(monkeypatch):
    """Make the first temp-file rename fail, then let every later rename through."""
    import internal.store.soul_map_io as soul_map_io

    real_replace = soul_map_io.os.replace
    calls = []

    def _flaky_replace(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(soul_map_io.os, "replace", _flaky_replace)


def _prediction_ids(trail) -> list:
    return [e["evidence"]["prediction_id"] for e in trail]


def test_failed_append_row_reaches_disk_on_next_successful_append(tmp_path, monkeypatch):
    """A row whose save failed must not vanish when a later append succeeds."""
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))
    failed = {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-failed"}}
    kept = {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-kept"}}

    _fail_first_replace(monkeypatch)
    bridge.append_learning_trail(failed, resolved_prediction_id="p-failed")
    bridge.append_learning_trail(kept, resolved_prediction_id="p-kept")

    on_disk = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert _prediction_ids(on_disk["learning_trail"]) == ["p-failed", "p-kept"]
    assert on_disk["resolved_prediction_ids"] == ["p-failed", "p-kept"]
    assert _prediction_ids(bridge.soul_map_state["learning_trail"]) == ["p-failed", "p-kept"]
    assert bridge.soul_map_state["resolved_prediction_ids"] == ["p-failed", "p-kept"]


def test_failed_append_row_reaches_disk_on_next_save_to_disk(tmp_path, monkeypatch):
    """A whole-bridge save after a failed append must also write the pending row."""
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))
    failed = {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-failed"}}

    _fail_first_replace(monkeypatch)
    bridge.append_learning_trail(failed, resolved_prediction_id="p-failed")
    bridge._save_to_disk()

    on_disk = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert _prediction_ids(on_disk["learning_trail"]) == ["p-failed"]
    assert on_disk["resolved_prediction_ids"] == ["p-failed"]


def test_failed_append_row_reaches_disk_through_a_fresh_bridge_per_event(tmp_path, monkeypatch):
    """Production builds a new bridge for every trail event, so a failed row must outlive its bridge."""
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    failed = {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-failed"}}
    kept = {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-kept"}}

    _fail_first_replace(monkeypatch)
    MindmapBridge(persistence_path=str(soul_path)).append_learning_trail(
        failed, resolved_prediction_id="p-failed"
    )
    MindmapBridge(persistence_path=str(soul_path)).append_learning_trail(
        kept, resolved_prediction_id="p-kept"
    )

    on_disk = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert _prediction_ids(on_disk["learning_trail"]) == ["p-failed", "p-kept"]
    assert on_disk["resolved_prediction_ids"] == ["p-failed", "p-kept"]


def test_row_committed_by_another_bridge_during_save_is_written_once(tmp_path, monkeypatch):
    """A pending row must not be replayed again after another bridge already committed it.

    The second bridge's commit runs inside the first bridge's save, after the first bridge
    queued its row. The first bridge's own write must then see that the row is already on disk.
    """
    import internal.council.mindmap_bridge as mindmap_bridge
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    first = MindmapBridge(persistence_path=str(soul_path))
    second = MindmapBridge(persistence_path=str(soul_path))
    real_write = mindmap_bridge.write_soul_map_committed
    interleaved = []

    def _write_after_second_commits(mutator, path):
        if not interleaved:
            interleaved.append(True)
            second.append_learning_trail(
                {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-second"}},
                resolved_prediction_id="p-second",
            )
        return real_write(mutator, path)

    monkeypatch.setattr(mindmap_bridge, "write_soul_map_committed", _write_after_second_commits)
    first.append_learning_trail(
        {"event_type": "prediction_resolved", "evidence": {"prediction_id": "p-first"}},
        resolved_prediction_id="p-first",
    )

    on_disk = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert sorted(_prediction_ids(on_disk["learning_trail"])) == ["p-first", "p-second"]
    assert sorted(on_disk["resolved_prediction_ids"]) == ["p-first", "p-second"]


def _timed_row(prediction_id: str) -> dict:
    # Replay dedupes on (event_type, time). A row without a time is never deduped, so set one.
    return {
        "time": f"t-{prediction_id}",
        "event_type": "prediction_resolved",
        "evidence": {"prediction_id": prediction_id},
    }


def test_row_already_committed_is_not_replayed_twice_by_a_later_write(tmp_path, monkeypatch):
    """A pending row that a commit already carried must stay once in trail and ledger.

    X fails to reach disk. The next append commits X with its own row. Another bridge then
    appends inside the window after that commit and before the drop, so the replay of X runs again.
    """
    import internal.council.mindmap_bridge as mindmap_bridge
    from internal.council.mindmap_bridge import MindmapBridge

    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {}}), encoding="utf-8")
    bridge = MindmapBridge(persistence_path=str(soul_path))
    later = MindmapBridge(persistence_path=str(soul_path))

    _fail_first_replace(monkeypatch)
    bridge.append_learning_trail(_timed_row("p-x"), resolved_prediction_id="p-x")

    real_write = mindmap_bridge.write_soul_map_committed
    injected = []

    def _write_then_later_appends(mutator, path):
        result = real_write(mutator, path)
        if not injected:
            injected.append(True)
            later.append_learning_trail(_timed_row("p-y"), resolved_prediction_id="p-y")
        return result

    monkeypatch.setattr(mindmap_bridge, "write_soul_map_committed", _write_then_later_appends)
    bridge.append_learning_trail(_timed_row("p-z"), resolved_prediction_id="p-z")

    on_disk = json.loads(soul_path.read_text(encoding="utf-8"))["soul_map_state"]
    assert sorted(_prediction_ids(on_disk["learning_trail"])) == ["p-x", "p-y", "p-z"]
    assert sorted(on_disk["resolved_prediction_ids"]) == ["p-x", "p-y", "p-z"]
