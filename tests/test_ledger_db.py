"""ledger.db module: connection settings, first-use import, applied keys, compare-and-swap."""

from __future__ import annotations

import json
import sqlite3

import pytest

from internal.council.weights import ConcurrentWeightUpdate
from internal.store import ledger_db


def _soul(tmp_path, blob=None, name="soul_map.json"):
    path = tmp_path / name
    if blob is not None:
        path.write_text(json.dumps(blob), encoding="utf-8")
    return str(path)


def _stored(conn, kind):
    return ledger_db.read_kind(conn, kind)


def test_connection_is_rollback_journal_full_sync_and_not_in_a_transaction(tmp_path):
    conn = ledger_db.connect(str(tmp_path / "ledger.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_a_ledger_beside_soul_map_json_is_ledger_db_and_another_name_gets_its_own(tmp_path):
    assert ledger_db.ledger_path_for(str(tmp_path / "soul_map.json")) == str(tmp_path / "ledger.db")
    assert ledger_db.ledger_path_for(str(tmp_path / "live.json")) == str(tmp_path / "live.json.ledger.db")


def test_import_seeds_every_weight_kind_then_drops_only_the_imported_keys(tmp_path):
    soul = _soul(
        tmp_path,
        {
            "adversarial_state": {
                "council_weights": {"quant": 1.4, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
                "signal_weights": {"hour": {"rsi_crossover": 1.3}},
                "impact_strength": 0.7,
            },
            "judge_weights": {"oracle": 0.5, "echo": 0.2, "pulse": 0.3},
            "keep": {"me": [1, 2, 3]},
        },
    )
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert")["quant"] == 1.4
        assert _stored(conn, "signal:hour")["rsi_crossover"] == 1.3
        assert _stored(conn, "signal:day")["macd_cross"] == 1.0
        assert _stored(conn, "impact") == {"strength": 0.7}
        assert _stored(conn, "judge") == {"oracle": 0.5, "echo": 0.2, "pulse": 0.3}
        assert ledger_db.weights_known(soul) is True
    assert json.load(open(soul)) == {"adversarial_state": {}, "keep": {"me": [1, 2, 3]}}


def test_missing_soul_map_seeds_defaults_that_are_not_known(tmp_path):
    soul = _soul(tmp_path)
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert") == {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    assert ledger_db.weights_known(soul) is False


def test_corrupt_soul_map_refuses_and_writes_no_weights(tmp_path):
    soul = _soul(tmp_path)
    open(soul, "w").write('{"adversarial_state": {"council_weights": {"quant": 1.')
    with pytest.raises(ledger_db.SoulMapUnreadable):
        with ledger_db.reader(soul):
            pass
    db = tmp_path / "ledger.db"
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        assert "weights" not in tables


def test_a_soul_map_that_appears_after_a_missing_import_is_imported_once_nothing_was_written(tmp_path):
    soul = _soul(tmp_path)
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert")["quant"] == 1.0
    open(soul, "w").write(json.dumps({"expert_weights": {"quant": 1.6}}))
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert")["quant"] == 1.6


def test_a_keyed_effect_applies_once(tmp_path):
    soul = _soul(tmp_path, {})
    with ledger_db.transaction(soul) as conn:
        assert ledger_db.apply_changes(conn, "expert", {"quant": 1.1}, source_id="p1") == (True, True)
    with ledger_db.transaction(soul) as conn:
        assert ledger_db.apply_changes(conn, "expert", {"quant": 1.2}, source_id="p1") == (False, False)
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert")["quant"] == 1.1
        row = conn.execute(
            "SELECT value_before, value_after FROM weight_applied WHERE source_id='p1' AND effect='expert:quant'"
        ).fetchone()
    assert row == (1.0, 1.1)


def test_compare_and_swap_is_a_where_value_check_inside_the_transaction(tmp_path):
    soul = _soul(tmp_path, {})
    with pytest.raises(ConcurrentWeightUpdate):
        with ledger_db.transaction(soul) as conn:
            ledger_db.apply_changes(conn, "expert", {"hype": 1.3}, expected={"hype": 1.0})
            ledger_db.apply_changes(conn, "expert", {"quant": 1.3}, expected={"quant": 0.9})
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert") == {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}


def test_an_error_inside_the_transaction_rolls_every_write_back(tmp_path):
    soul = _soul(tmp_path, {})
    with pytest.raises(RuntimeError):
        with ledger_db.transaction(soul) as conn:
            ledger_db.apply_changes(conn, "expert", {"quant": 1.5}, source_id="x")
            raise RuntimeError("boom")
    with ledger_db.reader(soul) as conn:
        assert _stored(conn, "expert")["quant"] == 1.0
        assert conn.execute("SELECT COUNT(*) FROM weight_applied").fetchone()[0] == 0


def test_a_corrupt_ledger_is_refused_not_replaced(tmp_path):
    soul = _soul(tmp_path, {})
    db = tmp_path / "ledger.db"
    db.write_bytes(b"not a sqlite file" * 40)
    junk = db.read_bytes()
    with pytest.raises(ledger_db.LedgerUnreadable):
        with ledger_db.reader(soul):
            pass
    assert db.read_bytes() == junk
