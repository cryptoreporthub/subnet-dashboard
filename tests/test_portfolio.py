"""§17.F3 — council paper portfolio from resolved picks."""

from __future__ import annotations

import fcntl
import json
import threading
import time

from fastapi.testclient import TestClient

from internal.portfolio.engine import build_portfolio_status
from server import app


def test_portfolio_status_empty():
    status = build_portfolio_status({"predictions": [], "resolved": []})
    assert status["empty"] is True
    assert status["summary"]["total_closed"] == 0
    assert status["summary"]["total_pnl_pct"] == 0.0
    assert status["summary"]["hold_tao_pnl_pct"] == 0.0
    assert status["closed_positions"] == []
    assert status["open_positions"] == []


def test_portfolio_follows_resolved_no_fake_fills():
    data = {
        "predictions": [
            {
                "id": "open-1",
                "netuid": 1,
                "name": "Pending",
                "direction": "up",
                "predicted_pct": 2.0,
                "created_at": "2026-07-01T00:00:00Z",
            }
        ],
        "resolved": [
            {
                "id": "r1",
                "netuid": 40,
                "name": "Ralph",
                "direction": "up",
                "predicted_pct": 5.0,
                "actual_pct": 10.0,
                "resolved_at": "2026-07-02T00:00:00Z",
            },
            {
                "id": "r2",
                "netuid": 3,
                "name": "Templar",
                "direction": "down",
                "predicted_pct": -3.0,
                "actual_pct": -4.0,
                "resolved_at": "2026-07-03T00:00:00Z",
            },
            {
                "id": "skip",
                "netuid": 9,
                "direction": "up",
                "predicted_pct": 1.0,
                "actual_pct": 2.0,
                "outcome": "duplicate",
            },
            {
                "id": "no-actual",
                "netuid": 10,
                "direction": "up",
                "predicted_pct": 1.0,
            },
        ],
    }
    status = build_portfolio_status(data)
    assert status["empty"] is False
    assert status["summary"]["total_closed"] == 2
    assert status["summary"]["win_count"] == 2
    # up+10 long → +10; down+-4 short → +4
    assert status["summary"]["total_pnl_pct"] == 14.0
    assert status["summary"]["avg_pnl_pct"] == 7.0
    assert status["summary"]["excess_vs_hold_tao_pct"] == 14.0
    assert status["summary"]["hold_tao_pnl_pct"] == 0.0
    assert len(status["open_positions"]) == 1
    assert status["open_positions"][0]["id"] == "open-1"
    assert all(p["id"] != "skip" for p in status["closed_positions"])


def test_portfolio_excludes_pump_and_shadow_rows():
    data = {
        "predictions": [],
        "resolved": [
            {
                "id": "council",
                "netuid": 40,
                "direction": "up",
                "predicted_pct": 5.0,
                "actual_pct": 10.0,
                "resolved_at": "2026-07-02T00:00:00Z",
            },
            {
                "id": "pump",
                "netuid": 41,
                "pick_source": "pump_lead",
                "direction": "up",
                "predicted_pct": 2.0,
                "actual_pct": 1.0,
                "resolved_at": "2026-07-02T00:00:00Z",
            },
            {
                "id": "shadow",
                "netuid": 42,
                "shadow": True,
                "direction": "up",
                "predicted_pct": 3.0,
                "actual_pct": 4.0,
                "resolved_at": "2026-07-02T00:00:00Z",
            },
        ],
    }
    status = build_portfolio_status(data)
    assert status["summary"]["total_closed"] == 1
    assert status["closed_positions"][0]["id"] == "council"


def test_portfolio_excludes_pump_and_shadow_rows_from_open_scope():
    status = build_portfolio_status(
        {
            "predictions": [
                {"id": "council", "netuid": 1, "direction": "up"},
                {"id": "pump", "netuid": 2, "direction": "up", "pick_source": "pump_lead"},
                {"id": "shadow", "netuid": 3, "direction": "up", "shadow": True},
            ],
            "resolved": [],
        }
    )
    assert [row["id"] for row in status["open_positions"]] == ["council"]
    assert status["eligibility"]["source"] == "data/predictions.json"


def test_api_portfolio_status_200():
    client = TestClient(app)
    resp = client.get("/api/portfolio/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "summary" in body
    assert "closed_positions" in body
    assert body["benchmark"] == "hold_tao"


def test_legacy_paper_portfolio_exposes_canonical_ledger_scope():
    body = TestClient(app).get("/api/paper-portfolio").json()
    assert body["source"] == "legacy_judge_portfolios"
    assert body["canonical_source"] == "data/predictions.json"
    assert "canonical" in body



def test_open_position_times_out_when_flock_held(tmp_path, monkeypatch):
    """T1: a held flock makes open_position fail fast; the write lands after release."""
    from internal.judges import portfolios

    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_LOCK_TIMEOUT_SECONDS", 0.3, raising=False)
    before = port_path.read_bytes()
    lock_path = str(port_path) + ".lock"
    holder = open(lock_path, "a+")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        errors = []

        def run():
            try:
                portfolios.open_position("oracle", {"id": "p1", "netuid": 1})
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        thread.start()
        thread.join(3)
        elapsed = time.monotonic() - started
        assert not thread.is_alive(), "open_position hung on a held flock"
        assert elapsed < 2
        assert errors and type(errors[0]).__name__ == "PortfolioLockTimeout"
        assert port_path.read_bytes() == before
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    portfolios.open_position("oracle", {"id": "p1", "netuid": 1})
    data = json.loads(port_path.read_text())
    assert data["oracle"]["open_positions"][0]["id"] == "p1"


def test_past_deadline_fails_fast_and_releases_mutex(tmp_path, monkeypatch):
    """T2: a deadline already in the past must not hang at remaining ~= -1.0."""
    from internal.judges import portfolios

    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    errors = []

    def run():
        try:
            with portfolios._portfolios_lock(deadline=time.monotonic() - 1.0):
                errors.append("entered")
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(2)
    assert not thread.is_alive(), "past-deadline acquire hung (RLock timeout=-1?)"
    assert errors and type(errors[0]).__name__ == "PortfolioLockTimeout"
    with portfolios._portfolios_lock():
        pass


def test_patched_lock_timeout_constant_is_honored(tmp_path, monkeypatch):
    """T11: PORTFOLIOS_LOCK_TIMEOUT_SECONDS is read inside the lock function."""
    from internal.judges import portfolios

    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_LOCK_TIMEOUT_SECONDS", 0.3, raising=False)
    lock_path = str(port_path) + ".lock"
    holder = open(lock_path, "a+")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        errors = []
        started = time.monotonic()

        def run():
            try:
                portfolios.open_position("oracle", {"id": "t11", "netuid": 2})
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(3)
        elapsed = time.monotonic() - started
        assert not thread.is_alive(), "patched timeout was ignored and the call hung"
        assert elapsed < 2
        assert errors and type(errors[0]).__name__ == "PortfolioLockTimeout"
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
