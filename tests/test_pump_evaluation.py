from internal.learning import pump_lead_train


def _row(i: int, *, correct: bool, actual_pct: float) -> dict:
    return {
        "id": str(i),
        "created_at": f"2026-08-{i + 1:02d}T00:00:00Z",
        "y": int(correct),
        "actual_pct": actual_pct,
    }


def test_chronological_split_keeps_latest_rows_in_holdout():
    rows = [_row(i, correct=True, actual_pct=3.0) for i in range(10)]

    splits = pump_lead_train.chronological_splits(rows)

    assert splits["train"][0]["id"] == "0"
    assert splits["holdout"][-1]["id"] == "9"
    assert max(r["created_at"] for r in splits["train"]) < min(
        r["created_at"] for r in splits["holdout"]
    )


def test_evaluation_does_not_qualify_without_holdout_sample(monkeypatch):
    rows = [_row(i, correct=True, actual_pct=3.0) for i in range(9)]
    monkeypatch.setattr(pump_lead_train, "collect_training_rows", lambda path=None: rows)

    report = pump_lead_train.build_pump_evaluation()

    assert report["status"] == "insufficient_sample"
    assert report["adaptation_gate"]["passed"] is False
