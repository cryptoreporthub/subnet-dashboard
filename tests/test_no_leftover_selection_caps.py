"""The rotation and the spotlight read the whole registry, not a fixed head of it."""

from __future__ import annotations

import json
from unittest.mock import patch

from internal.council import selector_scheduler as sched
from internal.learning.dpick_spotlight import _registry_subnets_for_spotlight


def test_rotation_receives_every_subnet_ranked_by_emission():
    subnets = [{"netuid": n, "emission": float(n)} for n in range(1, 41)]
    scheduler = sched.SelectorScheduler(refresh_minutes=60)
    seen = {}

    def _rotate(subnet_ids=None, **_):
        seen["ids"] = subnet_ids
        return {"daily_output": {"decisions": []}, "feedback_loop": {}}

    with patch("fetchers.taomarketcap.get_all_subnets", return_value=subnets), patch(
        "internal.council.orchestrator.Orchestrator"
    ) as orch_cls, patch("internal.learning.trail_bus.emit_disposition_shift"), patch.object(
        scheduler, "_schedule"
    ):
        orch_cls.return_value.run_daily_rotation.side_effect = _rotate
        scheduler._tick()

    assert seen["ids"] == list(range(40, 0, -1))


def test_spotlight_registry_read_returns_every_tradable_row(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    registry = {str(n): {"netuid": n} for n in range(1, 131)}
    (tmp_path / "config" / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("internal.subnets.tradable.tradable_subnets", lambda rows: rows)

    assert len(_registry_subnets_for_spotlight()) == 130
