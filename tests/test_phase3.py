"""
Unit + integration tests for Phase 3:
- Calibration / precision curve
- Retrain scheduler
- 3-judge paper portfolios
- New server endpoints
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import internal.council.calibration as calibration
import internal.council.judge_portfolio as judge_portfolio
import internal.council.retrain_scheduler as retrain_scheduler
import internal.council.resolver as resolver
import internal.council.weights as weights


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Keep all Phase 3 persistence inside a temp directory."""
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", str(tmp_path / "calibration.json"))
    monkeypatch.setattr(calibration, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(retrain_scheduler, "RETRAIN_HISTORY_PATH", str(tmp_path / "retrain_history.json"))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(judge_portfolio, "JUDGE_PORTFOLIOS_PATH", str(tmp_path / "judge_portfolios.json"))
    monkeypatch.setattr(judge_portfolio, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    # Disable scheduler background thread in tests.
    monkeypatch.setenv("DISABLE_RETRAIN_SCHEDULER", "1")

    # Re-initialize server globals so endpoint tests use the isolated paths.
    try:
        import server
        server._judge_portfolio_manager = judge_portfolio.JudgePortfolioManager()
        server._retrain_scheduler = retrain_scheduler.RetrainScheduler()
    except Exception:
        pass


@pytest.fixture
def sample_predictions() -> List[Dict[str, Any]]:
    return [
        {"status": "resolved", "correct": True, "confidence": 0.05},
        {"status": "resolved", "correct": False, "confidence": 0.08},
        {"status": "resolved", "correct": True, "confidence": 0.15},
        {"status": "resolved", "correct": True, "confidence": 0.25},
        {"status": "resolved", "correct": True, "confidence": 0.95},
        {"status": "resolved", "correct": True, "confidence": 0.98},
    ]


@pytest.fixture
def empty_predictions() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def sample_subnets() -> List[Dict[str, Any]]:
    return [
        {"netuid": 1, "name": "Alpha", "price": 10.0, "price_change_24h": 5.0, "emission": 3.0, "apy": 40.0, "volume": 1_000_000},
        {"netuid": 2, "name": "Beta", "price": 20.0, "price_change_24h": 2.0, "emission": 2.0, "apy": 30.0, "volume": 800_000},
        {"netuid": 3, "name": "Gamma", "price": 30.0, "price_change_24h": -1.0, "emission": 1.5, "apy": 25.0, "volume": 600_000},
        {"netuid": 4, "name": "Delta", "price": 40.0, "price_change_24h": -4.0, "emission": 1.0, "apy": 20.0, "volume": 400_000},
        {"netuid": 5, "name": "Epsilon", "price": 50.0, "price_change_24h": 0.0, "emission": 0.5, "apy": 15.0, "volume": 200_000},
    ]


# ---------------------------------------------------------------------------
# Calibration tests
# ---------------------------------------------------------------------------

def test_compute_calibration_curve_bins_predictions(sample_predictions):
    snapshot = calibration.compute_calibration_curve(sample_predictions)
    assert "curve" in snapshot
    assert len(snapshot["curve"]) == 10
    assert "monotonic" in snapshot
    assert "mean_precision" in snapshot
    assert "last_updated" in snapshot

    # 0-10% bin should have 2 predictions, 1 correct -> precision 0.5
    bin_0_10 = next(b for b in snapshot["curve"] if b["bin_label"] == "0-10%")
    assert bin_0_10["total"] == 2
    assert bin_0_10["correct"] == 1
    assert bin_0_10["precision"] == 0.5

    # 90-100% bin should have 2 predictions, 2 correct -> precision 1.0
    bin_90_100 = next(b for b in snapshot["curve"] if b["bin_label"] == "90-100%")
    assert bin_90_100["total"] == 2
    assert bin_90_100["correct"] == 2
    assert bin_90_100["precision"] == 1.0


def test_compute_calibration_curve_derives_confidence_from_predicted_pct():
    predictions = [
        {"status": "resolved", "correct": True, "predicted_pct": 5.0},
        {"status": "resolved", "correct": False, "predicted_pct": 15.0},
    ]
    snapshot = calibration.compute_calibration_curve(predictions)
    bin_0_10 = next(b for b in snapshot["curve"] if b["bin_label"] == "0-10%")
    bin_10_20 = next(b for b in snapshot["curve"] if b["bin_label"] == "10-20%")
    assert bin_0_10["total"] == 1
    assert bin_10_20["total"] == 1


def test_compute_calibration_curve_persists(tmp_path, sample_predictions):
    calibration.compute_calibration_curve(sample_predictions)
    assert os.path.exists(calibration.CALIBRATION_PATH)
    with open(calibration.CALIBRATION_PATH, "r") as f:
        data = json.load(f)
    assert data["mean_precision"] == round(5 / 6, 4)


def test_get_monotonicity_score_true_when_rising():
    curve = [
        {"total": 1, "precision": 0.1},
        {"total": 1, "precision": 0.2},
        {"total": 1, "precision": 0.3},
    ]
    assert calibration.get_monotonicity_score(curve) is True


def test_get_monotonicity_score_false_when_falling():
    curve = [
        {"total": 1, "precision": 0.3},
        {"total": 1, "precision": 0.2},
        {"total": 1, "precision": 0.1},
    ]
    assert calibration.get_monotonicity_score(curve) is False


def test_get_calibration_snapshot_default():
    snapshot = calibration.get_calibration_snapshot()
    assert len(snapshot["curve"]) == 10
    assert snapshot["mean_precision"] == 0.0


def test_recalibrate_reads_from_predictions_file(tmp_path):
    data = {
        "predictions": [],
        "resolved": [
            {"status": "resolved", "correct": True, "confidence": 0.95},
            {"status": "resolved", "correct": False, "confidence": 0.85},
        ],
    }
    with open(calibration.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)
    snapshot = calibration.recalibrate(calibration.PREDICTIONS_PATH)
    assert snapshot["mean_precision"] == 0.5


# ---------------------------------------------------------------------------
# Retrain scheduler tests
# ---------------------------------------------------------------------------

def test_retrain_scheduler_next_run_time():
    scheduler = retrain_scheduler.RetrainScheduler(hour_utc=5, minute_utc=30)
    now = datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)
    nxt = scheduler._next_run_time(now)
    assert nxt == datetime(2026, 6, 28, 5, 30, 0, tzinfo=timezone.utc)

    now = datetime(2026, 6, 27, 5, 0, 0, tzinfo=timezone.utc)
    nxt = scheduler._next_run_time(now)
    assert nxt == datetime(2026, 6, 27, 5, 30, 0, tzinfo=timezone.utc)


def test_retrain_scheduler_run_cycle(tmp_path, monkeypatch):
    scheduler = retrain_scheduler.RetrainScheduler(
        predictions_path=resolver.PREDICTIONS_PATH,
        history_path=retrain_scheduler.RETRAIN_HISTORY_PATH,
    )

    now = datetime.now(timezone.utc)
    data = {
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "resolved": [],
    }
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)

    subnets = [{"netuid": 1, "price": 115.0}]
    report = scheduler.run_cycle(subnets)

    assert report["predictions_resolved"] == 1
    assert report["accuracy"] == 1.0
    assert "precision_curve" in report
    assert "weights_snapshot" in report
    assert os.path.exists(retrain_scheduler.RETRAIN_HISTORY_PATH)

    status = scheduler.get_status()
    assert status["last_retrain"] == report["timestamp"]
    assert status["last_report"] == report


def test_retrain_scheduler_status_before_any_run():
    scheduler = retrain_scheduler.RetrainScheduler()
    status = scheduler.get_status()
    assert status["last_retrain"] is None
    assert status["last_report"] is None
    assert "next_retrain" in status


# ---------------------------------------------------------------------------
# Judge portfolio tests
# ---------------------------------------------------------------------------

def test_open_and_close_position(tmp_path):
    manager = judge_portfolio.JudgePortfolioManager()
    pos = manager.open_position(
        judge_id="evidence",
        netuid=1,
        subnet_name="Alpha",
        entry_price=100.0,
        direction="long",
        entry_signal="rsi oversold",
    )
    assert pos["netuid"] == 1
    assert pos["direction"] == "long"
    assert "position_id" in pos

    closed = manager.close_position(pos["position_id"], exit_price=110.0)
    assert closed is not None
    assert closed["realized_return_pct"] == 10.0
    assert closed["outcome"] == "win"


def test_close_short_position():
    manager = judge_portfolio.JudgePortfolioManager()
    pos = manager.open_position(
        judge_id="adversarial",
        netuid=2,
        subnet_name="Beta",
        entry_price=100.0,
        direction="short",
        entry_signal="overbought",
    )
    closed = manager.close_position(pos["position_id"], exit_price=90.0)
    assert closed["realized_return_pct"] == 10.0
    assert closed["outcome"] == "win"

    pos2 = manager.open_position(
        judge_id="adversarial",
        netuid=3,
        subnet_name="Gamma",
        entry_price=100.0,
        direction="short",
        entry_signal="overbought",
    )
    closed2 = manager.close_position(pos2["position_id"], exit_price=110.0)
    assert closed2["realized_return_pct"] == -10.0
    assert closed2["outcome"] == "loss"


def test_win_loss_classification():
    manager = judge_portfolio.JudgePortfolioManager()
    pos_win = manager.open_position("evidence", 1, "A", 100.0, "long", "signal")
    pos_loss = manager.open_position("evidence", 2, "B", 100.0, "long", "signal")
    pos_even = manager.open_position("evidence", 3, "C", 100.0, "long", "signal")

    assert manager.close_position(pos_win["position_id"], 110.0)["outcome"] == "win"
    assert manager.close_position(pos_loss["position_id"], 90.0)["outcome"] == "loss"
    assert manager.close_position(pos_even["position_id"], 100.0)["outcome"] == "breakeven"


def test_leaderboard_sorting():
    manager = judge_portfolio.JudgePortfolioManager()
    # Evidence: one win.
    p1 = manager.open_position("evidence", 1, "A", 100.0, "long", "signal")
    manager.close_position(p1["position_id"], 120.0)
    # Adversarial: one loss.
    p2 = manager.open_position("adversarial", 2, "B", 100.0, "long", "signal")
    manager.close_position(p2["position_id"], 80.0)
    # Chaos: breakeven.
    p3 = manager.open_position("chaos", 3, "C", 100.0, "long", "signal")
    manager.close_position(p3["position_id"], 100.0)

    board = manager.get_leaderboard()
    assert len(board) == 3
    assert board[0]["judge_id"] == "evidence"
    assert board[1]["judge_id"] == "chaos"
    assert board[2]["judge_id"] == "adversarial"
    assert board[0]["rank"] == 1


def test_portfolio_persistence(tmp_path):
    manager = judge_portfolio.JudgePortfolioManager()
    pos = manager.open_position("evidence", 1, "A", 100.0, "long", "signal")
    manager.close_position(pos["position_id"], 110.0)

    manager2 = judge_portfolio.JudgePortfolioManager(path=judge_portfolio.JUDGE_PORTFOLIOS_PATH)
    portfolio = manager2.get_portfolio("evidence")
    assert portfolio["stats"]["total_trades"] == 1
    assert portfolio["stats"]["wins"] == 1


def test_update_unrealized():
    manager = judge_portfolio.JudgePortfolioManager()
    pos = manager.open_position("evidence", 1, "A", 100.0, "long", "signal")
    manager.update_unrealized({1: 115.0})
    portfolio = manager.get_portfolio("evidence")
    updated_pos = portfolio["positions"][0]
    assert updated_pos["current_return_pct"] == 15.0


def test_rebalance_adjusts_size():
    manager = judge_portfolio.JudgePortfolioManager()
    pos = manager.open_position("evidence", 1, "A", 100.0, "long", "signal", size=1.0)
    rebalanced = manager.rebalance("evidence", 1, "long", confidence=0.9)
    assert rebalanced["size"] > 1.0


def test_evidence_daily_action_opens_longs(sample_subnets):
    manager = judge_portfolio.JudgePortfolioManager()
    prices = {sn["netuid"]: sn["price"] for sn in sample_subnets}
    result = manager.daily_judge_action("evidence", sample_subnets, [], prices)
    assert result["action"] == "open_longs"
    assert len(result["opened"]) <= 3
    for pos in result["opened"]:
        assert pos["direction"] == "long"


def test_adversarial_daily_action_opens_shorts(sample_subnets):
    manager = judge_portfolio.JudgePortfolioManager()
    prices = {sn["netuid"]: sn["price"] for sn in sample_subnets}
    result = manager.daily_judge_action("adversarial", sample_subnets, [], prices)
    assert result["action"] == "open_shorts"
    assert len(result["opened"]) <= 3
    for pos in result["opened"]:
        assert pos["direction"] == "short"


def test_chaos_daily_action_random_explore(sample_subnets):
    manager = judge_portfolio.JudgePortfolioManager()
    prices = {sn["netuid"]: sn["price"] for sn in sample_subnets}
    result = manager.daily_judge_action("chaos", sample_subnets, [], prices)
    assert result["action"] == "random_explore"
    assert len(result["opened"]) <= 3


def test_adjust_judge_weight_updates_soul_map(tmp_path):
    manager = judge_portfolio.JudgePortfolioManager()
    # Evidence outperforms.
    p1 = manager.open_position("evidence", 1, "A", 100.0, "long", "signal")
    manager.close_position(p1["position_id"], 120.0)
    # Adversarial underperforms.
    p2 = manager.open_position("adversarial", 2, "B", 100.0, "long", "signal")
    manager.close_position(p2["position_id"], 80.0)
    # Chaos breakeven.
    p3 = manager.open_position("chaos", 3, "C", 100.0, "long", "signal")
    manager.close_position(p3["position_id"], 100.0)

    manager.adjust_judge_weights()
    weights = manager.get_judge_weights()
    assert weights["evidence"] > 1.0
    assert weights["adversarial"] < 1.0


# ---------------------------------------------------------------------------
# Server endpoint tests
# ---------------------------------------------------------------------------

def test_server_calibration_curve_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/calibration/curve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["curve"]) == 10
    assert "monotonic" in body


def test_server_retrain_status_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/retrain/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "next_retrain" in body


def test_server_retrain_trigger_endpoint(tmp_path, monkeypatch):
    from server import app, _retrain_scheduler
    from fastapi.testclient import TestClient

    monkeypatch.setattr(_retrain_scheduler, "predictions_path", resolver.PREDICTIONS_PATH)
    monkeypatch.setattr(_retrain_scheduler, "history_path", retrain_scheduler.RETRAIN_HISTORY_PATH)

    now = datetime.now(timezone.utc)
    data = {
        "predictions": [
            {
                "netuid": 29,
                "reference_price": 20.0,
                "predicted_pct": 5.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "resolved": [],
    }
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)

    client = TestClient(app)
    resp = client.post("/api/retrain/trigger")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["report"]["predictions_resolved"] == 1


def test_server_judge_portfolios_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/judge-portfolios")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["portfolios"].keys()) == {"evidence", "adversarial", "chaos"}
    assert len(body["leaderboard"]) == 3


def test_server_judge_portfolio_detail_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/judge-portfolios/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["portfolio"]["judge_id"] == "evidence"


def test_server_judge_portfolios_leaderboard_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/judge-portfolios/leaderboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["leaderboard"]) == 3


def test_server_judge_portfolios_action_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/api/judge-portfolios/action")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["actions"].keys()) == {"evidence", "adversarial", "chaos"}
    assert len(body["leaderboard"]) == 3
