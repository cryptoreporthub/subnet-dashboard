"""Static scheduler boot contract — every inventoried scheduler has start_* + boot site.

Part B of the pump desk scheduler contract sweep (#1139).
Uses source inspection only (no real background threads).
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
BOOT = (REPO / "internal" / "background_boot.py").read_text(encoding="utf-8")

# name | module with start helper | expected boot marker in background_boot (or exception)
# Boot markers are substrings that must appear in background_boot.py OR documented exception.
INVENTORIED = [
    {
        "name": "prediction_resolver",
        "start_symbol": "start_prediction_resolver_scheduler",
        "module": "internal/council/resolver_scheduler.py",
        "boot_marker": "_start_resolver",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "daily_pick",
        "start_symbol": "start_pick_schedulers",
        "module": "internal/council/pick_scheduler.py",
        "boot_marker": "_start_pick_schedulers",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "hour_pick",
        "start_symbol": "start_pick_schedulers",
        "module": "internal/council/pick_scheduler.py",
        "boot_marker": "_start_pick_schedulers",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "pump_ladder",
        "start_symbol": "ensure_pump_ladder_scheduler",
        "module": "internal/pump/scheduler.py",
        "boot_marker": "_start_pump_ladder",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "pump_desk_snapshot",
        "start_symbol": "start_pump_desk_snapshot_scheduler",
        "module": "internal/pump/desk_snapshot_scheduler.py",
        "boot_marker": "_start_pump_desk_snapshot_scheduler",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "score_snapshot",
        "start_symbol": "start_score_snapshot_scheduler",
        "module": "internal/council/score_snapshots.py",
        "boot_marker": "_start_score_snapshot_scheduler",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "pick_selection_audit",
        "start_symbol": "start_pick_audit_scheduler",
        "module": "internal/council/pick_audit_scheduler.py",
        "boot_marker": "_start_pick_audit_scheduler",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "learning_outcome_snapshot",
        "start_symbol": "start_outcome_snapshot_scheduler",
        "module": "internal/learning/outcome_snapshot_scheduler.py",
        "boot_marker": "_start_outcome_snapshot_scheduler",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "calibration_snapshot",
        "start_symbol": "start_calibration_snapshot_scheduler",
        "module": "internal/message_intel/calibration_snapshot_scheduler.py",
        "boot_marker": "_start_calibration_snapshot_scheduler",
        "exception": None,
        "in_liveness": True,
    },
    {
        "name": "selector_rotation",
        "start_symbol": "start_selector_scheduler",
        "module": "internal/council/selector_scheduler.py",
        "boot_marker": None,
        "exception": "started as side-effect of start_prediction_resolver_scheduler",
        "in_liveness": True,
    },
    {
        "name": "dev_radar_github",
        "start_symbol": "start_dev_radar_github_scheduler",
        "module": "internal/dev_radar/github_sync.py",
        "boot_marker": "_start_dev_radar_github_scheduler",
        "exception": None,
        "in_liveness": False,  # no LivenessTracker
    },
    {
        "name": "whale_ledger_warm",
        "start_symbol": "schedule_interval_seconds",
        "module": "internal/background_boot.py",
        "boot_marker": "_start_whale_warm_scheduler",
        "exception": "inline schedule_interval_seconds in background_boot (no LivenessTracker)",
        "in_liveness": False,
    },
    {
        "name": "registry_freshness",
        "start_symbol": "start_background_sync",
        "module": "internal/freshness.py",
        "boot_marker": "start_background_sync",
        "exception": None,
        "in_liveness": False,
    },
    {
        "name": "calibration_auto_retrain",
        "start_symbol": "maybe_trigger_auto_retrain",
        "module": "internal/calibration/scheduler.py",
        "boot_marker": None,
        "exception": "post-resolver hook (not an interval scheduler boot)",
        "in_liveness": True,  # when get_liveness() called
    },
]

# Documented follow-ups: have start helpers / LivenessTracker but no boot wiring.
FOLLOW_UPS_NO_BOOT = [
    {
        "name": "adversarial_scheduler",
        "start_symbol": "start_adversarial_scheduler",
        "module": "internal/scheduler.py",
    },
    {
        "name": "indicator_scheduler",
        "start_symbol": "start_indicator_scheduler",
        "module": "internal/indicators/indicator_scheduler.py",
    },
]


def test_inventoried_schedulers_have_start_and_boot_site():
    missing = []
    for item in INVENTORIED:
        mod_path = REPO / item["module"]
        assert mod_path.is_file(), f"missing module {item['module']}"
        src = mod_path.read_text(encoding="utf-8")
        if item["start_symbol"] not in src and item["module"] != "internal/background_boot.py":
            # whale warm uses schedule_interval_seconds imported into background_boot
            missing.append(f"{item['name']}: start symbol {item['start_symbol']} absent in {item['module']}")
            continue
        if item["module"] == "internal/background_boot.py":
            if item["start_symbol"] not in BOOT:
                missing.append(f"{item['name']}: {item['start_symbol']} absent in background_boot")
        if item["boot_marker"]:
            if item["boot_marker"] not in BOOT:
                missing.append(
                    f"{item['name']}: boot marker {item['boot_marker']} absent in background_boot"
                )
        else:
            assert item["exception"], f"{item['name']} needs boot_marker or exception"
    assert not missing, "scheduler contract gaps:\n" + "\n".join(missing)


def test_pump_desk_boot_logs_start_result():
    """Boot must capture start() and route through _log_scheduler_start (never swallow)."""
    assert "_log_scheduler_start" in BOOT
    pattern = (
        r"result = start_pump_desk_snapshot_scheduler\(.*\)\s*\n"
        r"\s*_log_scheduler_start\(\"pump_desk_snapshot\""
    )
    assert re.search(pattern, BOOT), "pump desk start result must be logged"
    checks = (
        ("pump_ladder", "ensure_pump_ladder_scheduler"),
        ("prediction_resolver", "start_prediction_resolver_scheduler"),
        ("daily_hour_pick", "start_pick_schedulers"),
    )
    for label, call in checks:
        marker = '_log_scheduler_start("' + label + '"'
        assert marker in BOOT, label
        assert call in BOOT


def test_follow_up_schedulers_exist_but_lack_boot():
    """Orphan start helpers — list as follow-ups, do not silently wire."""
    for item in FOLLOW_UPS_NO_BOOT:
        mod = (REPO / item["module"]).read_text(encoding="utf-8")
        assert item["start_symbol"] in mod
        # Must NOT be invoked from background_boot today
        assert item["start_symbol"] not in BOOT


def test_log_scheduler_start_warns_on_false(monkeypatch, caplog):
    import logging

    import internal.background_boot as boot

    caplog.set_level(logging.WARNING, logger="internal.background_boot")
    boot._log_scheduler_start("pump_desk_snapshot", {"started": False, "reason": "disabled"})
    assert any(
        "started=False" in r.getMessage() and "pump_desk_snapshot" in r.getMessage()
        for r in caplog.records
    )
