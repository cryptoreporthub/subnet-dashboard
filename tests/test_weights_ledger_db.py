"""W1: learned weights and their applied keys live in ledger.db, not soul_map.json."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

PROD_KEYS = (
    "soul_map_state",
    "feedback_logs",
    "prediction_resolver_scheduler",
    "liveness",
    "score_snapshot_scheduler",
    "adversarial_state",
    "simivision_convictions",
    "expert_weights",
    "judge_weights",
    "simivision_convictions_updated_at",
)


def _prod_shaped_soul_map() -> dict:
    return {
        "soul_map_state": {"learning_trail": [{"n": i} for i in range(5)], "resolved_prediction_ids": ["a", "b"]},
        "feedback_logs": [{"id": i, "note": "x" * 200} for i in range(40)],
        "prediction_resolver_scheduler": {"last_cycle": {"ok": True}},
        "liveness": {"resolver": {"at": "2026-11-01T00:00:00Z"}},
        "score_snapshot_scheduler": {"last": "2026-11-01"},
        "adversarial_state": {
            "council_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.05, "technical": 1.0},
            "signal_weights": {"hour": {"rsi_crossover": 1.3}, "day": {"macd_cross": 0.8}},
            "impact_strength": 1.25,
            "last_weight_update": "2026-11-01T00:00:00+00:00",
            "calibration": {"history": [1]},
        },
        "simivision_convictions": {"1": 0.5},
        "expert_weights": {"quant": 1.2, "hype": 0.9, "dark_horse": 1.05, "technical": 1.0},
        "judge_weights": {"oracle": 0.4, "echo": 0.3, "pulse": 0.3},
        "simivision_convictions_updated_at": "2026-11-01T00:00:00Z",
    }


@pytest.fixture
def soul(tmp_path):
    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps(_prod_shaped_soul_map(), indent=2), encoding="utf-8")
    return path


def _db_value(tmp_path, kind, name):
    conn = sqlite3.connect(str(tmp_path / "ledger.db"))
    try:
        row = conn.execute("SELECT value FROM weights WHERE kind=? AND name=?", (kind, name)).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def test_fixture_has_all_ten_production_keys(soul):
    blob = json.loads(soul.read_text())
    assert tuple(blob) == PROD_KEYS
    assert len(blob["feedback_logs"]) == 40


DROPPED_AFTER_IMPORT = ("judge_weights",)


def _expected_after_import() -> dict:
    """The prod-shaped blob minus the keys ledger.db now owns. expert_weights stays: compaction needs it."""
    blob = _prod_shaped_soul_map()
    for key in DROPPED_AFTER_IMPORT:
        blob.pop(key)
    adv = blob["adversarial_state"]
    for key in ("council_weights", "signal_weights", "impact_strength", "last_weight_update"):
        adv.pop(key)
    return blob


def test_first_use_import_returns_the_values_soul_map_held(soul, tmp_path):
    from internal.council.weights import load_impact_strength, load_signal_weights, load_weights
    from internal.judges.weights import load_judge_weights

    path = str(soul)
    assert load_weights(path) == {"quant": 1.2, "hype": 0.9, "dark_horse": 1.05, "technical": 1.0}
    assert load_signal_weights(path)["hour"]["rsi_crossover"] == 1.3
    assert load_signal_weights(path)["day"]["macd_cross"] == 0.8
    assert load_signal_weights(path)["hour"]["macd_cross"] == 1.0
    assert load_impact_strength(path) == 1.25
    assert load_judge_weights(path) == {"oracle": 0.4, "echo": 0.3, "pulse": 0.3}
    assert (tmp_path / "ledger.db").exists(), "weights were not imported into ledger.db"


def test_the_import_drops_only_the_weight_keys_and_leaves_every_other_key_byte_for_byte(soul):
    from internal.council.weights import load_weights

    original = json.loads(soul.read_text())
    load_weights(str(soul))
    text = soul.read_text()
    after = json.loads(text)
    assert tuple(after) == tuple(k for k in PROD_KEYS if k != "judge_weights")
    assert "council_weights" not in after["adversarial_state"]
    assert "signal_weights" not in after["adversarial_state"]
    assert "impact_strength" not in after["adversarial_state"]
    assert after["expert_weights"] == original["expert_weights"]
    assert after["adversarial_state"]["calibration"] == {"history": [1]}
    assert len(after["feedback_logs"]) == 40
    for key in after:
        if key == "adversarial_state":
            continue
        assert json.dumps(after[key], indent=2) == json.dumps(original[key], indent=2), key
    assert text == json.dumps(_expected_after_import(), indent=2)


def test_a_redirected_ledger_never_strips_the_soul_map_it_imported_from(soul, tmp_path, monkeypatch):
    """LEDGER_DB_PATH stands in for the real data dir under test, so the real soul_map must keep its keys."""
    from internal.store import ledger_db

    before = soul.read_bytes()
    monkeypatch.setattr(ledger_db, "_REPO_SOUL_MAP", str(soul))
    monkeypatch.setenv("LEDGER_DB_PATH", str(tmp_path / "elsewhere" / "ledger.db"))
    assert ledger_db.weights_known(str(soul)) is True
    assert (tmp_path / "elsewhere" / "ledger.db").exists()
    assert soul.read_bytes() == before


def test_weight_writers_leave_every_soul_map_key_byte_for_byte_untouched(soul, tmp_path):
    from internal.council.weights import load_weights, nudge_expert, nudge_impact_strength, nudge_signal_weight
    from internal.judges.weights import nudge_judge

    path = str(soul)
    load_weights(path)
    before = soul.read_bytes()
    assert nudge_expert("quant", True, path) == 1.22
    nudge_signal_weight("hour", "rsi_crossover", False, path)
    nudge_impact_strength(True, "small", path)
    assert nudge_judge("oracle", True, path) == 0.42
    assert soul.read_bytes() == before, "a weight writer changed soul_map.json"
    assert _db_value(tmp_path, "expert", "quant") == 1.22
    assert _db_value(tmp_path, "judge", "oracle") == 0.42


def test_non_weight_soul_map_writes_round_trip_after_import(soul):
    from internal.council.weights import load_weights
    from internal.store.soul_map_io import read_soul_map, write_soul_map

    load_weights(str(soul))
    write_soul_map(lambda blob: blob.update(liveness={"resolver": {"at": "later"}}), str(soul))
    blob = read_soul_map(str(soul))
    expected = _expected_after_import()
    expected["liveness"] = {"resolver": {"at": "later"}}
    assert blob == expected
    assert blob["feedback_logs"] == _prod_shaped_soul_map()["feedback_logs"]


def test_missing_soul_map_seeds_defaults_and_creates_no_soul_map(tmp_path):
    from internal.council.weights import DEFAULT_WEIGHTS, load_weights

    path = tmp_path / "soul_map.json"
    assert load_weights(str(path)) == DEFAULT_WEIGHTS
    assert not path.exists()
    assert (tmp_path / "ledger.db").exists()


def test_corrupt_soul_map_fails_closed_then_imports_once_repaired(tmp_path):
    from internal.council.weights import load_weights, nudge_expert
    from internal.store.ledger_db import LedgerUnreadable

    path = tmp_path / "soul_map.json"
    path.write_text('{"adversarial_state": {"council_weights": {"quant": 1.5', encoding="utf-8")
    torn = path.read_bytes()
    with pytest.raises(LedgerUnreadable):
        load_weights(str(path))
    assert nudge_expert("quant", True, str(path)) is None
    assert path.read_bytes() == torn
    path.write_text(json.dumps({"expert_weights": {"quant": 1.5}}), encoding="utf-8")
    assert load_weights(str(path))["quant"] == 1.5


def test_corrupt_ledger_db_is_not_replaced_by_defaults(soul, tmp_path):
    from internal.council.weights import load_weights, nudge_expert
    from internal.store.ledger_db import LedgerUnreadable

    db = tmp_path / "ledger.db"
    db.write_bytes(b"this is not a sqlite database" * 50)
    junk = db.read_bytes()
    with pytest.raises(LedgerUnreadable):
        load_weights(str(soul))
    assert nudge_expert("quant", True, str(soul)) is None
    assert db.read_bytes() == junk


def test_connection_is_rollback_journal_full_sync(soul, tmp_path):
    from internal.store import ledger_db

    conn = ledger_db.connect(str(tmp_path / "ledger.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_concurrent_nudges_lose_no_update(soul, tmp_path):
    from internal.council.weights import load_signal_weights, nudge_signal_weight

    path = str(soul)
    errors = []

    def run():
        try:
            for _ in range(10):
                nudge_signal_weight("hour", "mfi_flow", True, path)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert load_signal_weights(path)["hour"]["mfi_flow"] == pytest.approx(1.8)


def test_expected_weights_compare_and_swap_refuses_a_stale_snapshot(soul):
    from internal.council.weights import ConcurrentWeightUpdate, load_weights, nudge_expert, save_weights

    path = str(soul)
    stale = load_weights(path)
    nudge_expert("hype", True, path)
    with pytest.raises(ConcurrentWeightUpdate):
        save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, path, expected_weights=stale)
    assert load_weights(path)["hype"] == 0.92
    fresh = load_weights(path)
    assert save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, path, expected_weights=fresh)
    assert load_weights(path)["hype"] == 1.0


def test_keyed_nudge_applies_once(soul):
    from internal.council.weights import load_weights, nudge_expert

    path = str(soul)
    assert nudge_expert("quant", True, path, source_id="feedback:one") == 1.22
    assert nudge_expert("quant", True, path, source_id="feedback:one") is None
    assert load_weights(path)["quant"] == 1.22
    assert nudge_expert("quant", True, path, source_id="feedback:two") == 1.24


def test_legacy_contrarian_slot_is_repaired_at_import(tmp_path):
    from internal.council.weights import DEFAULT_WEIGHTS, load_weights

    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"expert_weights": {"quant": 1.7, "contrarian": 1.9}}), encoding="utf-8")
    (tmp_path / "predictions.json").write_text(json.dumps({"resolved": [], "pending": []}), encoding="utf-8")
    weights = load_weights(str(path))
    assert weights == DEFAULT_WEIGHTS
    assert "contrarian" not in weights


def test_pump_blend_weights_live_in_ledger_db_not_calibration_json(tmp_path):
    from internal.learning import pump_calibration as pc

    cal_path = str(tmp_path / "pump_calibration.json")
    cal = pc.load_calibration(cal_path)
    assert cal["blend_weights"]["volume"] == 0.30
    cal = pc._online_update_blend_weights(
        cal, {"correct": True, "signal_snapshot": {"volume_intensity": 1.0}}, path=cal_path
    )
    pc.save_calibration(cal, cal_path)
    assert "blend_weights" not in json.loads((tmp_path / "pump_calibration.json").read_text())
    assert _db_value(tmp_path, "pump_blend", "volume") == cal["blend_weights"]["volume"]
    assert pc.load_calibration(cal_path)["blend_weights"] == cal["blend_weights"]


def test_rebalance_script_saves_to_ledger_db(soul, tmp_path, monkeypatch):
    import runpy
    import sys

    data = tmp_path / "data"
    data.mkdir()
    (data / "soul_map.json").write_text(soul.read_text(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["rebalance_expert_weights.py", "--save"])
    monkeypatch.delenv("LEDGER_DB_PATH", raising=False)
    root = __import__("os").path.dirname(__import__("os").path.dirname(__file__))
    monkeypatch.syspath_prepend(root)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(root + "/scripts/rebalance_expert_weights.py", run_name="__main__")
    assert exc.value.code == 0
    conn = sqlite3.connect(str(data / "ledger.db"))
    try:
        got = conn.execute("SELECT value FROM weights WHERE kind='expert' AND name='quant'").fetchone()[0]
    finally:
        conn.close()
    assert got == 1.1
