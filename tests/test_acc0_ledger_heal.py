"""Acc-0 — daily pick ledger heal + epoch reset footgun."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from internal.learning.ledger_heal import (
    archive_predictions_epoch,
    heal_daily_pick_ledger,
)
from internal.learning.loop_health import build_learning_loop_health


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sample_pick(netuid: int = 15, price: float = 1.23) -> dict:
    return {
        "action": "long",
        "final_confidence": 0.485,
        "subnet": {"netuid": netuid, "name": f"SN{netuid}", "price": price},
        "prediction": {
            "predicted_pct": 2.5,
            "horizon_hours": 4,
            "reference_price": price,
        },
    }


def test_heal_backfills_gap(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [
            {
                "date": _today(),
                "action": "long",
                "pick": _sample_pick(),
                "market_context": {},
            }
        ],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": True, "last_run_at": datetime.now(timezone.utc).isoformat()},
    )

    summary = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert summary["ok"] is True
    assert summary["healed"] is True

    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["gap"] is False


def test_heal_uses_prediction_reference_price(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    pick = {
        "action": "long",
        "subnet": {"netuid": 15, "name": "SN15"},
        "prediction": {"reference_price": 0.0198846, "predicted_pct": 2.5, "horizon_hours": 4},
    }
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": pick, "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    summary = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert summary["healed"] is True
    assert summary["netuid"] == 15


def test_heal_idempotent(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    first = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    second = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert first["healed"] is True
    assert second["healed"] is False
    assert second["reason"] == "ledger_present"

    data = json.loads(preds.read_text(encoding="utf-8"))
    day_rows = [
        r
        for r in data.get("predictions", [])
        if r.get("horizon_type") == "day" and not r.get("shadow")
    ]
    assert len(day_rows) == 1


def test_heal_dry_run_no_write(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    summary = heal_daily_pick_ledger(dry_run=True, daily_picks_path=str(daily))
    assert summary["dry_run"] is True
    assert summary["would_record"] == 15
    data = json.loads(preds.read_text(encoding="utf-8"))
    assert data.get("predictions") == []


def test_epoch_reset_reheals_or_downgrades(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    archive = tmp_path / "archive"
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": _sample_pick(), "market_context": {}}],
    )
    _write_json(
        preds,
        {
            "predictions": [{"netuid": 99, "horizon_type": "day", "status": "pending"}],
            "resolved": [],
            "stats": {"pending": 1},
        },
    )

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr("internal.learning.ledger_heal.ARCHIVE_DIR", str(archive))
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": True, "last_run_at": datetime.now(timezone.utc).isoformat()},
    )

    summary = archive_predictions_epoch()
    assert summary["ok"] is True
    assert summary["archive_path"] is not None

    data = json.loads(preds.read_text(encoding="utf-8"))
    assert data.get("predictions")  # reheal should add today's row
    day_rows = [r for r in data["predictions"] if r.get("horizon_type") == "day"]
    assert any(int(r.get("netuid", 0)) == 15 for r in day_rows)

    report = build_learning_loop_health(
        daily_picks_path=str(daily),
        predictions_path=str(preds),
        soul_path=str(tmp_path / "missing_soul.json"),
    )
    assert report["ledger"]["gap"] is False


def test_heal_uses_prediction_reference_price(tmp_path, monkeypatch):
    daily = tmp_path / "daily_picks.json"
    preds = tmp_path / "predictions.json"
    pick = {
        "action": "long",
        "subnet": {"netuid": 15, "name": "SN15"},
        "prediction": {"reference_price": 0.0198846, "predicted_pct": 2.5, "horizon_hours": 4},
    }
    _write_json(
        daily,
        [{"date": _today(), "action": "long", "pick": pick, "market_context": {}}],
    )
    _write_json(preds, {"predictions": [], "resolved": [], "stats": {"pending": 0}})

    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    summary = heal_daily_pick_ledger(dry_run=False, daily_picks_path=str(daily))
    assert summary["healed"] is True
    assert summary["netuid"] == 15
