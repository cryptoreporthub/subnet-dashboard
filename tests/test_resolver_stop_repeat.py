"""A repeated stop() reports the lifecycle as persisted when the state is already on disk.

The second write has nothing to change, so it returns DECLINED. Base counted that as
persisted. Head counted only APPLIED, so a repeated stop reported not persisted.
"""

from __future__ import annotations

from internal.council import resolver_scheduler


def test_repeated_stop_still_reports_lifecycle_persisted(tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}")
    sched = resolver_scheduler.PredictionResolverScheduler(soul_map_path=str(soul))

    first = sched.stop()
    second = sched.stop()
    third = sched.stop()

    assert first.get("lifecycle_persisted") is True
    assert second.get("lifecycle_persisted") is True, second
    assert third.get("lifecycle_persisted") is True, third
    assert "pending" not in second and "pending" not in third
