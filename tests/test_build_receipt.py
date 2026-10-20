"""The snapshot build must run with no write timeout, and it must log its cost receipt."""

import json
import logging

import pytest

from internal import build_cost


@pytest.fixture
def isolated_build(tmp_path, monkeypatch):
    from internal.council import score_snapshots as snaps

    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json"))
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: ([{"netuid": 1, "name": "A"}], "test"))
    monkeypatch.setattr(
        "server._get_subnets_with_source", lambda timeout=4.0: ([{"netuid": 1, "name": "A"}], "test")
    )
    monkeypatch.setattr("server._market_context_with_weights", lambda subnets: {})
    build_cost.end()
    yield snaps
    build_cost.end()


@pytest.mark.parametrize("timeout", [0, -1])
def test_build_runs_inline_when_the_write_timeout_is_not_positive(isolated_build, monkeypatch, timeout):
    snaps = isolated_build
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", timeout)
    result = snaps.write_full_universe_snapshot()
    assert result.get("ok") is True, result
    assert "error" not in result
    published = json.loads(open(snaps.SCORE_SNAPSHOTS_PATH).read())
    cost = published["coverage"]["timing"]["build_cost"]
    assert cost["build_id"]


def test_build_logs_one_receipt_line_with_the_cost_block(isolated_build, monkeypatch, caplog):
    snaps = isolated_build
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 30)
    with caplog.at_level(logging.INFO, logger=snaps.logger.name):
        result = snaps.write_full_universe_snapshot()
    assert result.get("ok") is True, result
    lines = [r.getMessage() for r in caplog.records if "score snapshot build receipt" in r.getMessage()]
    assert len(lines) == 1
    receipt = json.loads(lines[0][lines[0].index("{") :])
    assert receipt["build_cost"]["build_id"]
    assert "rpc_calls" in receipt["build_cost"]


def test_unmeasured_build_omits_the_cost_block(isolated_build, monkeypatch):
    snaps = isolated_build
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(build_cost, "end", lambda: {})
    result = snaps.write_full_universe_snapshot()
    assert result.get("ok") is True, result
    published = json.loads(open(snaps.SCORE_SNAPSHOTS_PATH).read())
    assert "build_cost" not in published["coverage"]["timing"]


def test_begin_warns_when_a_build_is_already_active(caplog):
    build_cost.end()
    build_cost.begin("first")
    with caplog.at_level(logging.WARNING, logger=build_cost.logger.name):
        build_cost.begin("second")
    build_cost.end()
    assert any("already active" in r.getMessage() for r in caplog.records)
