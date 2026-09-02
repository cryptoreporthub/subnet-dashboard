from __future__ import annotations

import json

from internal.learning import predictions_store


def _stale_payload() -> dict:
    return {
        "predictions": [
            {
                "id": "stale-migration-row",
                "netuid": 29,
                "status": "pending",
                "phase_at_prediction": "MARKUP",
                "expert": "contrarian",
                "pick_source": "council",
                "evidence_population": "stale_population",
                "evidence_source": "stale_source",
            }
        ],
        "resolved": [],
        "stats": {},
    }


def _write_stale_payload(path) -> bytes:
    original = json.dumps(_stale_payload(), indent=2).encode("utf-8")
    path.write_bytes(original)
    return original


def test_load_predictions_migrates_in_memory_without_rewriting(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    original = _write_stale_payload(path)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    before_mtime_ns = path.stat().st_mtime_ns

    loaded = predictions_store.load_predictions()

    row = loaded["predictions"][0]
    assert row["phase_at_prediction"] == "EARLY"
    assert row["expert"] == "dark_horse"
    assert row["evidence_population"] == "council_published"
    assert row["evidence_source"] == "council"
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == before_mtime_ns
    assert not path.with_name(path.name + ".tmp").exists()


def test_load_predictions_persist_true_writes_migrations(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_stale_payload(path)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))

    predictions_store.load_predictions(persist=True)

    stored = json.loads(path.read_text(encoding="utf-8"))
    row = stored["predictions"][0]
    assert row["phase_at_prediction"] == "EARLY"
    assert row["expert"] == "dark_horse"
    assert row["evidence_population"] == "council_published"
    assert row["evidence_source"] == "council"


def test_writer_save_persists_in_memory_migrations_with_mutation(tmp_path, monkeypatch):
    path = tmp_path / "predictions.json"
    _write_stale_payload(path)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))

    loaded = predictions_store.load_predictions()
    loaded["predictions"][0]["status"] = "resolved"
    predictions_store.save_predictions(loaded)

    stored = json.loads(path.read_text(encoding="utf-8"))
    row = stored["predictions"][0]
    assert row["status"] == "resolved"
    assert row["phase_at_prediction"] == "EARLY"
    assert row["expert"] == "dark_horse"
    assert row["evidence_population"] == "council_published"
    assert row["evidence_source"] == "council"