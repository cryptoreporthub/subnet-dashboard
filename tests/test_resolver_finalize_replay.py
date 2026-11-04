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
        and (r.get("decision") or {}).get("prediction_id") == PREDICTION_ID
    ]


def _trail_rows(soul_path) -> list:
    data = json.loads(soul_path.read_text(encoding="utf-8"))
    trail = (data.get("soul_map_state") or {}).get("learning_trail") or []
    return [
        e
        for e in trail
        if e.get("event_type") == "prediction_resolved"
        and (e.get("evidence") or {}).get("prediction_id") == PREDICTION_ID
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
