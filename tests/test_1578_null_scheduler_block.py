import json

import pytest

from internal.council import resolver_scheduler
from internal.store.soul_map_io import WriteOutcome

SUMMARY = {
    "run_at": "2026-11-23T00:00:00+00:00",
    "cycle_generation": 1,
    "resolver_cycle_id": "c1",
    "ok": True,
}


def _write_lifecycle(sched, _path):
    return sched._persist_lifecycle_state()


def _write_summary(sched, _path):
    return sched._persist_cycle_summary_locked(dict(SUMMARY), force=True, owned_cycle=True)


WRITERS = [_write_lifecycle, _write_summary]


def _scheduler(path):
    return resolver_scheduler.PredictionResolverScheduler(
        soul_map_path=str(path), refresh_minutes=15
    )


@pytest.mark.parametrize("write", WRITERS, ids=["lifecycle", "cycle_summary"])
def test_null_scheduler_block_is_healed_on_write(tmp_path, write):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps({"prediction_resolver_scheduler": None, "adversarial_state": {"keep": 1}}),
        encoding="utf-8",
    )
    result = write(_scheduler(soul), str(soul))
    stored = json.loads(soul.read_text(encoding="utf-8"))
    assert result.outcome == WriteOutcome.APPLIED, result.detail
    assert isinstance(stored["prediction_resolver_scheduler"], dict)
    assert stored["adversarial_state"] == {"keep": 1}


@pytest.mark.parametrize(
    "block",
    [{"prediction_resolver_scheduler": None, "adversarial_state": {"keep": 1}}, {"adversarial_state": {"keep": 1}}],
    ids=["null", "missing"],
)
def test_declined_summary_into_unset_block_leaves_file_untouched(tmp_path, block):
    soul = tmp_path / "soul_map.json"
    original = json.dumps(block)
    soul.write_text(original, encoding="utf-8")
    invalid = {k: v for k, v in SUMMARY.items() if k != "cycle_generation"}
    result = _scheduler(soul)._persist_cycle_summary_locked(invalid, force=True, owned_cycle=True)
    assert result.outcome == WriteOutcome.DECLINED, result.detail
    assert soul.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("write", WRITERS, ids=["lifecycle", "cycle_summary"])
def test_non_null_non_dict_scheduler_block_still_fails_closed(tmp_path, write):
    soul = tmp_path / "soul_map.json"
    original = json.dumps({"prediction_resolver_scheduler": [1]})
    soul.write_text(original, encoding="utf-8")
    result = write(_scheduler(soul), str(soul))
    assert result.outcome == WriteOutcome.PERSIST_ERROR
    assert soul.read_text(encoding="utf-8") == original
