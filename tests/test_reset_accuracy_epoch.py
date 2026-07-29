"""Accuracy epoch reset archives resolved rows and clears trust stats."""

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reset_council_accuracy_epoch.py"
_spec = importlib.util.spec_from_file_location("reset_council_accuracy_epoch", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
reset_accuracy_epoch = _mod.reset_accuracy_epoch


def test_reset_archives_resolved_and_clears_stats(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pred_path = data_dir / "predictions.json"
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [{"id": "p1", "netuid": 1, "status": "pending", "horizon_type": "hour"}],
                "resolved": [
                    {
                        "id": "r1",
                        "netuid": 2,
                        "status": "resolved",
                        "outcome": "hit",
                        "correct": True,
                        "expert": "quant",
                    },
                    {
                        "id": "r2",
                        "netuid": 3,
                        "status": "resolved",
                        "outcome": "miss",
                        "correct": False,
                        "expert": "hype",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    report = reset_accuracy_epoch(dry_run=False, reset_weights=False, label="test")
    assert report["resolved_archived"] == 2
    assert report["pending_kept"] == 1
    assert report["new_stats"]["correct"] == 0
    assert report["new_stats"]["wrong"] == 0

    live = json.loads(pred_path.read_text(encoding="utf-8"))
    assert len(live["resolved"]) == 0
    assert len(live["predictions"]) == 1
    assert live["accuracy_epoch"]["prior_graded"] == 2

    archive_files = list((data_dir / "predictions_archive").glob("*.json"))
    assert len(archive_files) == 1
    archived = json.loads(archive_files[0].read_text(encoding="utf-8"))
    assert len(archived["resolved"]) == 2
