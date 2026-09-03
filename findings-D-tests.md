# Workstream D — Tests & Correctness (commit 44fd2fb7)

## D1 — Full suite: COMPLETED (after env provisioning)
Run1: 117 collection errors exit 2 (apscheduler missing). Retry: 97 collection errors exit 2 (slowapi x95, sentry_sdk x1, aiocache x1) — all pinned in requirements.txt (slowapi==0.1.9, sentry-sdk==2.19.0, aiocache==0.12.3) -> environment gap, not repo defect. After installing pinned versions, final run summary verbatim: `145 failed, 2489 passed, 4 skipped, 5 warnings in 146.75s (0:02:26)`. Note: APScheduler installed 3.11.3 vs requirements pin 3.10.4 (drift).

## D2 — stall_guard file: COMPLETED
pytest tests/test_loop_stall_guard.py -vv --tb=long > stall_guard_traceback.txt; D2_EXIT=1; wc -c = 6533; sha256 = e643e3e368b75ff41a8411c8492bd863ea6c6dcf8d83057e64ccf5d1b1046bc3. Summary: `3 failed, 7 passed, 1 warning in 0.65s`. Failures: test_revive_recycles_running_scheduler_in_guard_age_window, test_revive_recycles_very_stale_running_scheduler, test_revive_false_on_ok_without_moving_mtime — all `assert False is True`.

## D3 — Naive/aware mixing: PARTIAL
Zero naive datetime.now() in internal/ (grep excluding timezone.utc -> empty). Dominant pattern: aware _utcnow_z() + fromisoformat(value.replace("Z","+00:00")). Mixing points:
1. internal/conviction_decay.py:55 `age = (now - datetime.fromisoformat(last_updated)).total_seconds()`; now = datetime.now(timezone.utc) (:48); fromisoformat yields NAIVE dt if stored string lacks offset -> aware-minus-naive TypeError; inside try (:54), except type UNVERIFIED.
2. internal/conviction_index/__init__.py:130-136 SAFE: naive dt assumed UTC (dt.replace(tzinfo=timezone.utc)).
3. internal/accuracy_lift/measure.py:26 fromisoformat(raw) after Z->+00:00; naive-input handling UNVERIFIED.
Other fromisoformat sites (approval/service.py:111, bots/mission_control.py:350, bots/sentinel.py:158, bots/shield.py:96, council/ab_benchmark.py:239, analytics/soul_weights_chip.py:14) use the Z-replace aware pattern.
