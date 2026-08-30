"""Passive occupancy capture tests (Patch D / M7). Observe-only — no timeout bump, no KILL."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from internal.council import occupancy_capture as oc
from internal.learning.loop_health import build_learning_loop_health


def setup_function():
    oc.reset()


def test_snapshot_marks_gil_unmeasurable_and_patch_d_open():
    snap = oc.snapshot()
    assert snap["patch_d"] == "OPEN"
    assert snap["gil"] == "not_passively_observable"
    assert snap["abandoned_block_hypothesis"] == "unproven"
    assert "not_passively_observable" in snap["checks"]["abandoned_worker_block"]["gil"]


def test_tick_start_records_overlap():
    oc.note_tick_start(1, overlapping=False)
    oc.note_tick_start(2, overlapping=True)
    snap = oc.snapshot()
    assert snap["checks"]["retry_spawn"]["overlapping_seen"] is True
    kinds = [e["kind"] for e in snap["checks"]["generation_survival"]["events"]]
    assert kinds.count("tick_start") == 2


def test_timeout_survival_probe_sees_running_future():
    def _hang():
        time.sleep(8)
        return None

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daily-pick-work")
    fut = pool.submit(_hang)
    oc.note_timeout(9, 90, fut)
    time.sleep(5.15)
    snap = oc.snapshot()
    survived = [
        e
        for e in snap["checks"]["generation_survival"]["events"]
        if e.get("kind") == "survival" and e.get("delay_s") == 5.0
    ]
    pool.shutdown(wait=True, cancel_futures=False)
    assert survived
    assert survived[0]["survived_past_timeout"] is True


def test_note_block_tmc_and_fcntl():
    oc.note_block("tmc_lock", 12.5, 3.0)
    oc.note_block("fcntl", 1.0, 0.5)
    snap = oc.snapshot()
    assert snap["checks"]["abandoned_worker_block"]["tmc_lock"]
    assert snap["checks"]["abandoned_worker_block"]["fcntl"]


def test_learning_health_includes_occupancy_capture():
    report = build_learning_loop_health()
    assert "occupancy_capture" in report
    assert report["occupancy_capture"]["patch_d"] == "OPEN"
