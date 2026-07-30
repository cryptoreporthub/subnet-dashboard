"""FQ-4 — combined angles effectiveness artifact + ops evidence."""

from __future__ import annotations

import json

from internal.ops.evidence import build_evidence_report
from internal.pump import combined_ledger


def _resolved_row(pid: str, *, correct: bool, pick_source: str) -> dict:
    return {
        "id": pid,
        "netuid": 11,
        "pick_source": pick_source,
        "correct": correct,
        "actual_pct": 2.5 if correct else -0.5,
        "predicted_pct": 2.0,
        "pump_claim": "COMBINED_EXP",
        "pump_badge": "COMBINED EXP",
        "outcome": "hit" if correct else "miss",
    }


def test_effectiveness_summary_pick_source_buckets(tmp_path, monkeypatch):
    ledger = tmp_path / "calls.json"
    out_dir = tmp_path / "outcomes"
    out_dir.mkdir()
    eff_path = out_dir / "combined_angles_effectiveness.json"
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(ledger))
    monkeypatch.setattr(combined_ledger, "EFFECTIVENESS_PATH", str(eff_path))

    ledger.write_text(json.dumps({"calls": [], "version": 1}))

    preds = {
        "resolved": [
            _resolved_row("a1", correct=True, pick_source="pump_combined_exp"),
            _resolved_row("a2", correct=False, pick_source="pump_combined_exp"),
            _resolved_row("b1", correct=True, pick_source="pump_lead"),
        ],
        "predictions": [],
    }
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: preds,
    )

    summary = combined_ledger.build_effectiveness_summary()
    assert summary["pick_source"]["pump_combined_exp"]["n"] == 2
    assert summary["pick_source"]["pump_combined_exp"]["hits"] == 1
    assert summary["pick_source"]["pump_lead"]["n"] == 1
    assert summary["gates"]["weights_locked"] is True
    assert summary["gates"]["tune_ready"] is False

    path = combined_ledger.save_effectiveness_artifact(summary)
    assert path == str(eff_path)
    saved = json.loads(eff_path.read_text())
    assert saved["angles"]["combined"]["n"] == 0


def test_effectiveness_links_call_to_prediction(tmp_path, monkeypatch):
    ledger = tmp_path / "calls.json"
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(ledger))
    monkeypatch.setattr(
        combined_ledger,
        "EFFECTIVENESS_PATH",
        str(tmp_path / "eff.json"),
    )
    monkeypatch.setattr(
        combined_ledger,
        "_grade_candidate_at_call",
        lambda *a, **k: None,
    )

    call = {
        "id": "c1",
        "created_at": "2026-07-29T12:00:00Z",
        "prediction_id": "pred99",
        "next_up_top": {"netuid": 9, "price": 1.0},
        "peer_top": {"netuid": 7, "price": 1.0},
    }
    ledger.write_text(json.dumps({"calls": [call], "version": 1}))

    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"resolved": [_resolved_row("pred99", correct=True, pick_source="pump_combined_exp")], "predictions": []},
    )

    summary = combined_ledger.build_effectiveness_summary()
    assert summary["ledger"]["graded_calls"] == 1
    assert summary["angles"]["combined"]["n"] == 1
    assert summary["angles"]["combined"]["hits"] == 1


def test_evidence_includes_combined_angles(tmp_path, monkeypatch):
    eff = tmp_path / "combined.json"
    eff.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-30T00:00:00Z",
                "angles": {"combined": {"n": 0, "hits": 0, "hit_rate": None}},
                "pick_source": {"pump_combined_exp": {"n": 0, "hits": 0, "hit_rate": None}},
            }
        )
    )
    monkeypatch.setattr(
        "internal.pump.combined_ledger.EFFECTIVENESS_PATH",
        str(eff),
    )
    monkeypatch.setattr(
        "internal.ops.evidence._read_json",
        lambda path: json.loads(eff.read_text()) if "combined_angles" in path else None,
    )

    report = build_evidence_report()
    assert "combined_angles" in report
    assert report["paths"]["combined_angles"] is not None
