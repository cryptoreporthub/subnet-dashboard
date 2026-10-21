"""A wedged pump_ladder tick must not hold heavy_job_slot forever."""

from __future__ import annotations

import threading
import time

import internal.pump.scheduler as scheduler_mod
from internal.heavy_job_gate import heavy_job_slot
from internal.pump.scheduler import PumpLadderScheduler


def _acquire_within(name: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        with heavy_job_slot(name) as ok:
            if ok:
                return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)


def test_hung_pump_tick_releases_heavy_slot(monkeypatch):
    monkeypatch.setattr(scheduler_mod, "PUMP_LADDER_BODY_STALL_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(PumpLadderScheduler, "_schedule_next", lambda self, _r: None)
    body_started = threading.Event()
    never = threading.Event()

    def hung_body(self):
        body_started.set()
        never.wait(timeout=30)
        return {"ok": True}

    monkeypatch.setattr(PumpLadderScheduler, "_tick_body", hung_body)
    sched = PumpLadderScheduler(refresh_minutes=20)
    sched._active = False

    tick = threading.Thread(target=sched._tick, daemon=True)
    tick.start()
    try:
        assert body_started.wait(timeout=2), "pump tick body never started"
        assert _acquire_within("prediction_resolver", seconds=2), (
            "heavy_job_slot still held by hung pump_ladder"
        )
        assert sched.liveness.snapshot()["status"] != "ok"
    finally:
        never.set()
        tick.join(timeout=5)
        assert not tick.is_alive()
