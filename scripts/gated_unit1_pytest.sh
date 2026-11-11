#!/usr/bin/env bash
# Unit 1 soul-map write-honesty — PR gate (expand when touching predictions ledger).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export DISABLE_BACKGROUND_SCANS=1
exec python -m pytest -q \
  tests/test_soul_map_io.py \
  tests/test_soul_map_io_failure.py \
  tests/test_endpoint_contract.py \
  tests/test_soul_map_write_honesty.py \
  tests/test_judge_weight_write_honesty.py \
  tests/test_prediction_loop_judge_rollback.py \
  tests/test_mindmap_pending_declined.py \
  tests/test_1578_plan_v31_weights_ledger.py \
  tests/test_1578_ci_lists_in_sync.py \
  tests/test_1578_ledger_single_writer.py \
  tests/test_1578_single_ledger_writer_boundary.py \
  tests/test_1578_commit_then_learn.py \
  tests/test_1578_archive_readers.py \
  tests/test_resolver_scheduler.py \
  tests/test_resolver_soul_map_read_wedge.py \
  tests/test_resolver_predictions_unreadable.py \
  tests/test_resolver_persist_honesty_outcomes.py \
  tests/test_compact_soul_map.py \
  tests/test_resolver_corrupt_ledger_tick.py \
  tests/test_phase3_mid_guards_orphan_revive.py::test_phase3_dark_region_telemetry_t1_5_and_persist_subtimers \
  tests/test_prediction_loop_closure.py \
  tests/test_predictions_store_contract.py \
  tests/test_expiry_ledger.py \
  tests/test_acc0_ledger_heal.py \
  tests/test_predictions_write_race.py \
  tests/test_tribunal_hero_live.py \
  tests/test_predictions_store_patch_contract.py \
  tests/test_dev_radar.py \
  tests/test_graded_chat.py \
  "$@"
