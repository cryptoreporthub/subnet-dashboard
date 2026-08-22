"""Tests for parallelized dpick per-subnet scoring.

Verifies that the ThreadPoolExecutor-based loop in select_daily_pick
produces results identical (order and content) to the sequential
behavior, respects DPICK_MAX_WORKERS, and keeps latency instrumentation
intact.
"""

import json
import threading
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from internal.council import daily_pick


def _make_subnet(netuid, total=50.0, conf=0.5, name=None):
    return {
        "netuid": netuid,
        "name": name or ("sn%d" % netuid),
        "symbol": "S%d" % netuid,
        "price_change_24h": 1.0,
    }


def _fake_score(sn, market_context):
    """Deterministic score payload mimicking state_vector output."""
    time.sleep(0.01)
    return {
        "total_score": 50.0 + float(sn["netuid"]),
        "confidence": 0.5,
        "expert_contributions": {"quant": 0.1},
        "scenario_tags": {},
    }


@pytest.fixture
def fast_latency(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_pick, "LATENCY_PATH", str(tmp_path / "lat.jsonl"))
    return tmp_path / "lat.jsonl"


class _Gate:
    """Tracks max concurrent scorers to verify worker cap."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def enter(self):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit(self):
        with self.lock:
            self.active -= 1


def _gated_score(gate, delay=0.05):
    def scorer(sn, market_context):
        gate.enter()
        try:
            time.sleep(delay)
            return _fake_score(sn, market_context)
        finally:
            gate.exit()

    return scorer


def _enter_select_patches(stack: ExitStack):
    stack.enter_context(patch.object(daily_pick, "tradable_subnets", side_effect=lambda s: s))
    stack.enter_context(
        patch.object(
            daily_pick,
            "audit_daily_pick",
            side_effect=lambda c, s: {"approved": True, "adjusted_confidence": 0.5},
        )
    )
    stack.enter_context(patch.object(daily_pick, "attach_council_prediction", return_value={}))
    stack.enter_context(patch.object(daily_pick, "pick_reasons", return_value=[]))
    stack.enter_context(
        patch.object(
            daily_pick,
            "unpack_score_learning_fields",
            return_value={
                "signal_impact": None,
                "signal_contributions": None,
                "active_signals": [],
            },
        )
    )


def test_parse_dpick_max_workers_invalid_and_cap():
    assert daily_pick._parse_dpick_max_workers("99") == 8
    assert daily_pick._parse_dpick_max_workers("0") == 4
    assert daily_pick._parse_dpick_max_workers("abc") == 4
    assert daily_pick._parse_dpick_max_workers("3") == 3


def test_parallel_results_match_sequential_order(fast_latency, monkeypatch):
    subnets = [_make_subnet(i) for i in range(8)]
    monkeypatch.setattr(daily_pick, "DPICK_MAX_WORKERS", 4)

    with ExitStack() as stack:
        stack.enter_context(patch.object(daily_pick, "score_subnet_for_day", side_effect=_fake_score))
        _enter_select_patches(stack)
        result = daily_pick.select_daily_pick(subnets, {})

    assert result["subnet"]["netuid"] == 7


def test_worker_cap_respected(fast_latency, monkeypatch):
    subnets = [_make_subnet(i) for i in range(10)]
    gate = _Gate()
    monkeypatch.setattr(daily_pick, "DPICK_MAX_WORKERS", 3)

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(daily_pick, "score_subnet_for_day", side_effect=_gated_score(gate))
        )
        _enter_select_patches(stack)
        daily_pick.select_daily_pick(subnets, {})

    assert gate.max_active <= 3


def test_parallel_faster_than_sequential(fast_latency, monkeypatch):
    subnets = [_make_subnet(i) for i in range(6)]
    gate = _Gate()
    monkeypatch.setattr(daily_pick, "DPICK_MAX_WORKERS", 6)

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(daily_pick, "score_subnet_for_day", side_effect=_gated_score(gate, delay=0.1))
        )
        _enter_select_patches(stack)
        t0 = time.perf_counter()
        daily_pick.select_daily_pick(subnets, {})
        elapsed = time.perf_counter() - t0

    assert elapsed < 0.45


def test_latency_rows_still_written(fast_latency, monkeypatch):
    subnets = [_make_subnet(i) for i in range(4)]
    monkeypatch.setattr(daily_pick, "DPICK_MAX_WORKERS", 2)

    with ExitStack() as stack:
        stack.enter_context(patch.object(daily_pick, "score_subnet_for_day", side_effect=_fake_score))
        _enter_select_patches(stack)
        daily_pick.select_daily_pick(subnets, {})

    rows = [json.loads(line) for line in fast_latency.read_text().strip().splitlines()]
    assert len(rows) == 4
    assert [r["netuid"] for r in rows] == [0, 1, 2, 3]


def test_scorer_exception_propagates(fast_latency, monkeypatch):
    subnets = [_make_subnet(i) for i in range(4)]
    monkeypatch.setattr(daily_pick, "DPICK_MAX_WORKERS", 2)

    def scorer(sn, market_context):
        if sn["netuid"] == 2:
            raise RuntimeError("boom")
        return _fake_score(sn, market_context)

    with ExitStack() as stack:
        stack.enter_context(patch.object(daily_pick, "score_subnet_for_day", side_effect=scorer))
        _enter_select_patches(stack)
        with pytest.raises(RuntimeError, match="boom"):
            daily_pick.select_daily_pick(subnets, {})
