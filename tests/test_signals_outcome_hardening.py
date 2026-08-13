"""Focused freshness and outcome-worker safety checks."""

import asyncio
import time
from unittest.mock import patch

import internal.message_intel.outcome_loop as outcome_loop
import internal.signals.routes as signal_routes


def test_empty_signal_cache_regenerates(monkeypatch):
    class Store:
        def query(self, **kwargs):
            return []

        def cache_is_stale(self):
            return True

    calls = []
    monkeypatch.setattr(signal_routes, "_get_store", lambda: Store())
    monkeypatch.setattr(
        signal_routes,
        "generate_signals",
        lambda persist=True: calls.append(persist)
        or {"signals": [{"subnet_id": 1}], "meta": {"count": 1}, "changed_signals": []},
    )
    monkeypatch.setattr(signal_routes, "_get_alerts", lambda: type("Alerts", (), {
        "check_system_alerts": lambda self: [],
        "record_signal_changes": lambda self, rows: [],
        "evaluate_correlation_alerts": lambda self, rows: [],
    })())
    monkeypatch.setattr(signal_routes, "get_signal_hub", lambda: type("Hub", (), {
        "broadcast": lambda self, *args: asyncio.sleep(0),
    })())
    monkeypatch.setattr(signal_routes, "_to_thread_timeout", lambda fn, timeout_s, label: _run(fn))

    async def run():
        return await signal_routes.api_signals(refresh=False, subnet_id=None)

    async def _run(fn):
        return fn()

    result = asyncio.run(run())
    assert result["signals"][0]["subnet_id"] == 1
    assert calls == [True]


def test_signal_regeneration_is_single_flight(monkeypatch):
    class Store:
        def query(self, **kwargs):
            return []

        def cache_is_stale(self):
            return True

    calls = []

    def generate(persist=True):
        calls.append(persist)
        time.sleep(0.05)
        return {"signals": [{"subnet_id": 1}], "meta": {"count": 1}, "changed_signals": []}

    monkeypatch.setattr(signal_routes, "_get_store", lambda: Store())
    monkeypatch.setattr(signal_routes, "generate_signals", generate)
    monkeypatch.setattr(signal_routes, "_get_alerts", lambda: type("Alerts", (), {
        "check_system_alerts": lambda self: [],
        "record_signal_changes": lambda self, rows: [],
        "evaluate_correlation_alerts": lambda self, rows: [],
    })())
    monkeypatch.setattr(signal_routes, "get_signal_hub", lambda: type("Hub", (), {
        "broadcast": lambda self, *args: asyncio.sleep(0),
    })())

    async def run():
        return await asyncio.gather(
            signal_routes.api_signals(refresh=False, subnet_id=None),
            signal_routes.api_signals(refresh=False, subnet_id=None),
        )

    results = asyncio.run(run())
    assert len(calls) == 1
    assert any(result["signals"][0]["subnet_id"] == 1 for result in results)
    assert any(result["meta"].get("source") == "refreshing" for result in results)


def test_outcome_progress_callback_touches_between_work(monkeypatch):
    from message_intel.price_tracker import PriceTracker

    class DB:
        def get_unresolved_outcomes(self):
            return []

    touches = []
    tracker = PriceTracker(db=DB(), progress_callback=lambda: touches.append(True))
    tracker.check_outcomes()
    assert len(touches) >= 2


def test_watchdog_refuses_replacement_when_old_thread_wedges(monkeypatch):
    class Old:
        _running = True

    old = Old()
    old._thread = type("Wedge", (), {
        "is_alive": lambda self: True,
        "join": lambda self, timeout: None,
    })()
    outcome_loop._tracker = old

    class New:
        def __init__(self, db=None, progress_callback=None):
            self._running = False

        def start_background_checks(self, interval=300):
            self._running = True

    with patch("message_intel.price_tracker.PriceTracker", New), patch(
        "internal.message_intel.store.get_db", return_value=None
    ):
        outcome_loop._restart_outcome_loop(interval=1)

    assert outcome_loop._tracker is old
    assert old._thread.is_alive()
    outcome_loop._tracker = None
