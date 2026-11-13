from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from internal.learning.predictions_store import PersistOutcome, PersistReason, PersistResult

import pytest
from internal.judges import portfolios


@pytest.fixture(autouse=True)
def _readable_portfolios(tmp_path, monkeypatch):
    """Recovery now fail-closes when the portfolio book is missing or unreadable."""
    port_path = tmp_path / "judge_portfolios.json"
    if not port_path.exists():
        port_path.write_text("{}")
    if not port_path.exists():
        port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    return port_path




def test_recovery_uses_canonical_finalize_and_resolves_status(tmp_path, monkeypatch):
    from internal.council import resolver
    from internal.council import price_reference
    from internal.learning import expired_recovery, predictions_store

    predictions_path = tmp_path / "predictions.json"
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    predictions_path.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "expired-1",
                        "netuid": 7,
                        "status": "expired",
                        "outcome": "expired",
                        "correct": None,
                        "direction": "up",
                        "reference_price": 100.0,
                        "predicted_pct": 5.0,
                        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", resolver.atomic_finalize_resolution)

    result = expired_recovery.recover_expired_predictions()
    saved = json.loads(predictions_path.read_text())
    row = saved["resolved"][0]

    assert result["recovered"] == 1
    assert row["status"] == "resolved"
    assert row["outcome"] == "hit"
    assert row["correct"] is True
    assert row["resolved_price"] == 110.0



_SHAPED_KEYS = ("ok", "reason", "error", "dry_run", "recovered", "skipped", "details")


def _expired_row(pred_id="expired-1"):
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    return {
        "id": pred_id,
        "netuid": 7,
        "status": "expired",
        "outcome": "expired",
        "correct": None,
        "direction": "up",
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
    }


def test_recovery_corrupt_ledger_returns_shaped_unreadable(tmp_path, monkeypatch):
    """T5: a corrupt ledger is a shaped refusal, and bytes are unchanged."""
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    path.write_bytes(b"{not json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    before = path.read_bytes()
    result = expired_recovery.recover_expired_predictions()
    assert result["ok"] is False
    assert result["reason"] == "ledger_unreadable"
    for key in _SHAPED_KEYS:
        assert key in result
    assert path.read_bytes() == before


def test_recovery_transient_ledger_read_returns_shaped_unreadable(tmp_path, monkeypatch):
    """T5: the reachable transient kind (not a raw OSError) is also shaped."""
    from internal.learning import expired_recovery, predictions_store
    from internal.store.soul_map_io import BlobRead
    from internal.store import soul_map_io

    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    before = path.read_bytes()
    monkeypatch.setattr(
        soul_map_io,
        "read_blob_checked",
        lambda _path: BlobRead("transient", None, error="EIO"),
    )
    # load_predictions imports read_blob_checked at call time or module time?
    # Patch both the io module and the store's bound name if present.
    if hasattr(predictions_store, "read_blob_checked"):
        monkeypatch.setattr(
            predictions_store,
            "read_blob_checked",
            lambda _path: BlobRead("transient", None, error="EIO"),
        )
    result = expired_recovery.recover_expired_predictions()
    assert result["ok"] is False
    assert result["reason"] == "ledger_unreadable"
    assert "transient" in str(result.get("error") or "")
    for key in _SHAPED_KEYS:
        assert key in result
    assert path.read_bytes() == before


def test_recovery_persist_refusal_uses_reason_value(tmp_path, monkeypatch):
    """T6: a persist refusal returns the full shape and reason.lock_timeout value."""
    from internal.council import resolver
    from internal.council import price_reference
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [], "resolved": [_expired_row()], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        predictions_store,
        "merge_ledger_changes",
        lambda *args, **kwargs: PersistResult(PersistOutcome.REFUSED, PersistReason.LOCK_TIMEOUT),
    )
    result = expired_recovery.recover_expired_predictions()
    assert result["ok"] is False
    assert result["reason"] == "lock_timeout"
    for key in _SHAPED_KEYS:
        assert key in result


def test_recovery_continues_after_judge_close_warning(tmp_path, monkeypatch):
    """T7: a close warning on row 1 does not skip finalizing row 2."""
    from internal.council import resolver
    from internal.council import price_reference
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    rows = [_expired_row("row-1"), _expired_row("row-2")]
    path.write_text(json.dumps({"predictions": [], "resolved": rows, "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    real_finalize = resolver.atomic_finalize_resolution

    def finalize(row, **kwargs):
        result = real_finalize(row, **kwargs)
        if row.get("id") == "row-1":
            warnings = list(row.get("side_effect_warnings") or [])
            if "on_prediction_resolved" not in warnings:
                warnings.append("on_prediction_resolved")
            row["side_effect_warnings"] = warnings
        return result

    monkeypatch.setattr(resolver, "atomic_finalize_resolution", finalize)
    result = expired_recovery.recover_expired_predictions()
    saved = json.loads(path.read_text())
    by_id = {row["id"]: row for row in saved["resolved"]}
    assert by_id["row-2"]["status"] == "resolved"
    assert by_id["row-2"]["outcome"] == "hit"
    assert result["ok"] is False
    assert result["reason"] == "judge_close_incomplete"
    assert result.get("incomplete_ids") == ["row-1"]


def test_recovery_close_deadline_does_not_include_price_hydration(tmp_path, monkeypatch):
    """T13: a slow price fetch must not spend the close deadline before the close."""
    from internal.council import resolver
    from internal.council import price_reference
    from internal.judges import portfolios, postmortems
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    port_path = tmp_path / "portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    row = _expired_row("hydrate-1")
    path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    if not port_path.exists():
        port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_LOCK_TIMEOUT_SECONDS", 0.25, raising=False)
    pending = {
        "id": "hydrate-1",
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
    }
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, pending)

    def slow_price(*args, **kwargs):
        time.sleep(0.4)
        return ("ok", 110.0, {"price_source": "hourly"})

    monkeypatch.setattr(price_reference, "price_at_resolve_at", slow_price)
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    result = expired_recovery.recover_expired_predictions()
    data = json.loads(port_path.read_text())
    assert result.get("ok") is not False or result.get("reason") != "judge_close_incomplete"
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))
    assert all(len(data[name]["closed_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_revoked_finalize_is_not_a_successful_recovery(tmp_path, monkeypatch):
    """A revoked cycle that skips judge closes must not be reported as recovery_ok."""
    from internal.council import resolver
    from internal.council import price_reference
    from internal.judges import portfolios
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    port_path = tmp_path / "portfolios.json"
    row = _expired_row("revoked-1")
    path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    if not port_path.exists():
        port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    pending = {
        "id": "revoked-1",
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
    }
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, pending)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    monkeypatch.setattr(resolver, "_cycle_writes_revoked_safe", lambda: True)
    result = expired_recovery.recover_expired_predictions()
    data = json.loads(port_path.read_text())
    assert result["ok"] is False
    assert result["reason"] == "judge_close_incomplete"
    assert "revoked-1" in (result.get("incomplete_ids") or [])
    assert all(len(data[name]["open_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_stale_close_warning_does_not_fail_recovery_when_positions_closed(tmp_path, monkeypatch):
    """A leftover side_effect_warning is not a fresh close failure if judges are closed."""
    from internal.council import resolver
    from internal.council import price_reference
    from internal.judges import portfolios
    from internal.learning import expired_recovery, predictions_store

    path = tmp_path / "predictions.json"
    port_path = tmp_path / "portfolios.json"
    row = _expired_row("stale-1")
    row["side_effect_warnings"] = ["on_prediction_resolved"]
    path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    if not port_path.exists():
        port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    pending = {
        "id": "stale-1",
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
    }
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, pending)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"), raising=False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    result = expired_recovery.recover_expired_predictions()
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))
    assert result.get("reason") != "judge_close_incomplete"
    assert result.get("ok") is not False or result.get("reason") != "judge_close_incomplete"
