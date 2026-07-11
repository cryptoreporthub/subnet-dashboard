"""Phase F — SQLite persistence + Soul-Map mirror (Agent A)."""

from __future__ import annotations

import json

import pytest

from internal.store import (
    count_decision_lineage,
    count_dispositions,
    get_store_stats,
    get_trail_rows,
    init_store,
    sqlite_available,
)
from internal.trace.store import TRACE_STORE_PATH, append_record, get_record, load_store


def _build_soul_map_with_dispositions(path, count: int = 24) -> None:
    decisions = [
        {
            "netuid": i + 1,
            "name": f"SN{i + 1}",
            "recommended_action": "accumulate" if i % 3 == 0 else "hold",
            "score": round(0.4 + (i % 5) * 0.1, 2),
        }
        for i in range(count)
    ]
    payload = {
        "soul_map_state": {
            "updated_at": "2026-07-11T06:00:00Z",
            "learning_trail": [],
            "last_selector_output": {"decisions": decisions},
            "decision_lineage": {
                "updated_at": "2026-07-11T06:00:00Z",
                "total_records": 3,
                "top_signal_types": [["pump_phase", 2], ["scenario_tag", 1]],
                "last_record": {"id": "tr_seed", "decision_type": "pick"},
            },
        },
        "adversarial_state": {
            "council_weights": {
                "quant": 1.0,
                "hype": 1.0,
                "dark_horse": 1.0,
                "technical": 1.0,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "store.db")
    trace_path = str(tmp_path / "decision_trace.json")
    soul_path = tmp_path / "soul_map.json"

    trace_path_obj = tmp_path / "decision_trace.json"
    trace_path_obj.write_text(
        json.dumps(
            {
                "meta": {"version": 1},
                "records": [
                    {
                        "id": "tr_json_1",
                        "created_at": "2026-07-11T05:00:00Z",
                        "decision_type": "pick",
                        "decision": {"action": "accumulate"},
                        "signals": [{"type": "pump_phase", "payload": {"phase": "STIRRING"}}],
                        "subnet": "Alpha",
                        "netuid": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _build_soul_map_with_dispositions(soul_path, count=24)

    monkeypatch.setenv("STORE_DB_PATH", db_path)
    monkeypatch.setenv("TRACE_STORE_PATH", trace_path)
    monkeypatch.setattr("internal.trace.store.TRACE_STORE_PATH", trace_path)
    monkeypatch.setattr("internal.trace.store._CANONICAL_TRACE_PATH", trace_path)
    monkeypatch.setattr("internal.store.db.STORE_DB_PATH", db_path)
    monkeypatch.setattr("internal.store.query.STORE_DB_PATH", db_path)
    monkeypatch.setattr("internal.store.soul_map_mirror.TRACE_STORE_PATH", trace_path)

    import internal.council.weights as weights_mod

    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", str(soul_path))

    # Re-bootstrap store module state after env patch
    import internal.store as store_mod

    store_mod._sqlite_ready = False
    store_mod._bootstrap()

    yield {
        "db_path": db_path,
        "trace_path": trace_path,
        "soul_path": str(soul_path),
    }


def test_get_trail_rows_returns_list(store_env):
    init_store()
    assert sqlite_available()
    rows = get_trail_rows(limit=10)
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]["id"] == "tr_json_1"


def test_init_store_backfills_dispositions_and_lineage(store_env):
    init_store()
    assert count_dispositions() >= 24
    assert count_decision_lineage() >= 1


def test_get_store_stats_shape(store_env):
    init_store()
    stats = get_store_stats()
    assert set(stats.keys()) >= {"trail_count", "disposition_count", "lineage_count"}
    assert stats["trail_count"] >= 1
    assert stats["disposition_count"] >= 24
    assert stats["lineage_count"] >= 1


def test_append_record_writes_json_and_sqlite(store_env):
    init_store()
    record = {
        "id": "tr_append_test",
        "created_at": "2026-07-11T06:10:00Z",
        "decision_type": "weight_change",
        "decision": {"expert": "quant", "delta": 0.02},
        "signals": [{"type": "judge_signal", "payload": {}}],
        "subnet": "Beta",
        "netuid": 2,
    }
    append_record(record)

    assert get_record("tr_append_test") is not None
    json_data = json.loads(open(store_env["trace_path"], encoding="utf-8").read())
    assert any(r.get("id") == "tr_append_test" for r in json_data.get("records") or [])

    rows = get_trail_rows(limit=50, signal="judge_signal")
    assert any(r.get("id") == "tr_append_test" for r in rows)


def test_load_store_compat_shape(store_env):
    init_store()
    data = load_store()
    assert "meta" in data
    assert isinstance(data.get("records"), list)
    assert any(r.get("id") == "tr_json_1" for r in data["records"])


def test_init_store_idempotent(store_env):
    init_store()
    first = get_store_stats()
    init_store()
    second = get_store_stats()
    assert second["trail_count"] == first["trail_count"]
    assert second["disposition_count"] == first["disposition_count"]


def test_custom_trace_path_stays_json_only(tmp_path, monkeypatch):
    """Isolated trace path (tests) must not require SQLite."""
    custom = str(tmp_path / "custom_trace.json")
    record = {
        "id": "tr_custom",
        "created_at": "2026-07-11T06:00:00Z",
        "decision_type": "pick",
        "decision": {},
        "signals": [],
    }
    append_record(record, path=custom)
    assert get_record("tr_custom", path=custom) is not None
