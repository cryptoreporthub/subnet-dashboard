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
    assert report["occupancy_capture"]["deployment"]["deployment_identity"] == "unknown"
    assert report["occupancy_capture"]["deployment"]["includes_pr_1008"] == "unknown"
    assert "stale_side_effects" in report["occupancy_capture"]["checks"]
    assert report["occupancy_capture"]["checks"]["stale_side_effects"]["reason"] == "not captured"
    ev3 = report["occupancy_capture"]["checks"]["abandoned_worker_block"]["evidence"]
    assert ev3["grade"] == "inconclusive"
    assert ev3["grade"] != "pass"


def test_provenance_unknown_never_pass_even_with_partial_env(monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "deadbeef")
    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    monkeypatch.delenv("FLY_ALLOC_ID", raising=False)
    monkeypatch.delenv("FLY_REGION", raising=False)
    monkeypatch.delenv("FLY_VM_SIZE", raising=False)
    snap = oc.snapshot()
    assert snap["deployment"]["deployment_identity"] == "unknown"
    assert snap["checks"]["thread_count"]["evidence"]["grade"] != "pass"


def test_check5_no_timestamp_at_write_sites():
    class _Fut:
        def running(self):
            return False

    oc.note_timeout(3, 90, _Fut())
    oc.note_persist("daily_picks.json", has_write_timestamp=False)
    snap = oc.snapshot()
    s = snap["checks"]["stale_side_effects"]
    assert s["status"] == "not_observable"
    assert s["reason"] == "checked; no timestamp at write sites"
    assert s["evidence"]["grade"] != "pass"


def test_check3_inconclusive_without_worker_logs():
    oc.note_block("tmc_lock", 80.0, 1.0)
    snap = oc.snapshot()
    block = snap["checks"]["abandoned_worker_block"]
    assert block["tmc_lock"]
    assert block["worker_log_correlation"]["available"] is True
    assert block["evidence"]["grade"] == "inconclusive"
    oc.reset()
    snap2 = oc.snapshot()
    assert snap2["checks"]["abandoned_worker_block"]["worker_log_correlation"]["available"] is False
    assert snap2["checks"]["abandoned_worker_block"]["evidence"]["grade"] == "inconclusive"
    assert "not inferred" in snap2["checks"]["abandoned_worker_block"]["evidence"]["note"]

