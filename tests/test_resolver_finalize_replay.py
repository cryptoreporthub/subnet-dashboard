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


def test_truthy_non_list_learning_trail_does_not_block_trail(isolated):
    _trace_path, soul_path = isolated
    soul_path.write_text(
        json.dumps({"soul_map_state": {"learning_trail": 1}}),
        encoding="utf-8",
    )

    _finalize_once()

    assert len(_trail_rows(soul_path)) == 1


@pytest.fixture
def canonical_sqlite_env(tmp_path, monkeypatch):
    """Canonical trace path backed by SQLite (JSON mirror may be empty or stale)."""
    db_path = str(tmp_path / "store.db")
    trace_path = str(tmp_path / "decision_trace.json")
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(json.dumps({"soul_map_state": {"learning_trail": []}}), encoding="utf-8")
    trace_path_obj = tmp_path / "decision_trace.json"
    trace_path_obj.write_text(json.dumps(trace_store._empty_store()), encoding="utf-8")

    monkeypatch.setenv("STORE_DB_PATH", db_path)
    monkeypatch.setenv("TRACE_STORE_PATH", trace_path)
    monkeypatch.setattr(trace_store, "TRACE_STORE_PATH", trace_path)
    monkeypatch.setattr(trace_store, "_CANONICAL_TRACE_PATH", trace_path)
    monkeypatch.setattr("internal.store.db.STORE_DB_PATH", db_path)
    monkeypatch.setattr("internal.store.query.STORE_DB_PATH", db_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul_path))
    monkeypatch.setattr(resolver, "on_prediction_resolved", lambda *_a, **_k: None)
    monkeypatch.setattr(pick_history, "finalize_from_prediction", lambda *_a, **_k: None)

    import internal.store as store_mod

    store_mod._sqlite_ready = False
    store_mod._bootstrap()
    assert store_mod.sqlite_available()

    from internal.store.query import record_trace_row

    record_trace_row(
        {
            "id": "tr_sqlite_existing",
            "created_at": "2026-07-01T00:30:00Z",
            "decision_type": "prediction_resolve",
            "decision": {"prediction_id": PREDICTION_ID, "outcome": "hit"},
            "signals": [],
            "subnet": "Replay Finalize",
            "netuid": 7,
        },
        db_path=db_path,
    )
    return trace_path_obj, soul_path, db_path


def test_has_decision_row_sees_sqlite_when_json_empty(canonical_sqlite_env):
    trace_path, _soul_path, _db_path = canonical_sqlite_env
    trace_path.write_text(json.dumps(trace_store._empty_store()), encoding="utf-8")

    assert trace_store.has_decision_row("prediction_resolve", PREDICTION_ID) is True


def test_replayed_finalize_skips_sqlite_lineage_when_json_empty(canonical_sqlite_env):
    trace_path, _soul_path, _db_path = canonical_sqlite_env
    trace_path.write_text(json.dumps(trace_store._empty_store()), encoding="utf-8")

    assert trace_store.has_decision_row("prediction_resolve", PREDICTION_ID)
    _finalize_once()
    _finalize_once()
    assert len(_lineage_rows(trace_path)) == 0
    assert trace_store.has_decision_row("prediction_resolve", PREDICTION_ID)
