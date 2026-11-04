"""resolver._save_json skips writes from cycles whose persist ownership was revoked."""

from __future__ import annotations

import json

import pytest

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler


@pytest.fixture
def predictions_file(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"marker": "original"}), encoding="utf-8")
    return str(path)


def _bind_cycle(sched, gen):
    """Bind a cycle timing owned by `sched` at `gen`, as the worker thread does."""
    timing = resolver_scheduler._CycleTiming()
    timing.set_owner_gen(gen, sched)
    token = resolver_scheduler._cycle_timing.set(timing)
    return token


def test_owner_cycle_write_lands(predictions_file):
    sched = resolver_scheduler.PredictionResolverScheduler()
    sched._persist_owner_gen = 1
    token = _bind_cycle(sched, 1)
    try:
        resolver._save_json(predictions_file, {"marker": "owner"}, caller="test")
    finally:
        resolver_scheduler._cycle_timing.reset(token)

    assert json.loads(open(predictions_file, encoding="utf-8").read()) == {"marker": "owner"}


def test_abandoned_cycle_write_is_skipped(predictions_file):
    sched = resolver_scheduler.PredictionResolverScheduler()
    sched._persist_owner_gen = 1
    token = _bind_cycle(sched, 1)
    try:
        sched._abandon_inflight_cycle()
        resolver._save_json(predictions_file, {"marker": "orphan"}, caller="test")
    finally:
        resolver_scheduler._cycle_timing.reset(token)

    assert json.loads(open(predictions_file, encoding="utf-8").read()) == {"marker": "original"}


def test_revocation_is_read_from_issuing_instance_not_global(predictions_file, monkeypatch):
    """Generations restart per instance; a different live scheduler must not revoke this cycle."""
    issuing = resolver_scheduler.PredictionResolverScheduler()
    issuing._persist_owner_gen = 1
    other = resolver_scheduler.PredictionResolverScheduler()
    other._persist_owner_gen = None
    monkeypatch.setattr(resolver_scheduler, "_scheduler", other)

    token = _bind_cycle(issuing, 1)
    try:
        resolver._save_json(predictions_file, {"marker": "owner"}, caller="test")
    finally:
        resolver_scheduler._cycle_timing.reset(token)

    assert json.loads(open(predictions_file, encoding="utf-8").read()) == {"marker": "owner"}


def test_unbound_thread_write_is_not_guarded(predictions_file):
    """Direct writers outside a scheduler cycle keep writing."""
    resolver._save_json(predictions_file, {"marker": "direct"}, caller="test")

    assert json.loads(open(predictions_file, encoding="utf-8").read()) == {"marker": "direct"}
