"""Seeding the cycle generation reads the soul map once, even when it has no scheduler key.

Base set the seeded flag on every completed pass. Head returned early when the
prediction_resolver_scheduler key was absent, so every cycle re-read the whole soul
map until the key appeared.
"""

from __future__ import annotations

import json

from internal.council import resolver_scheduler
from internal.store import soul_map_io


def test_seed_reads_soul_map_once_when_scheduler_key_is_absent(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"other": {}}))
    reads = {"n": 0}
    real = soul_map_io.read_blob_checked

    def counting(path):
        reads["n"] += 1
        return real(path)

    monkeypatch.setattr(soul_map_io, "read_blob_checked", counting)
    sched = resolver_scheduler.PredictionResolverScheduler(soul_map_path=str(soul))
    reads["n"] = 0  # count only the seeding reads, not construction
    sched._ensure_cycle_generation_seeded()
    sched._ensure_cycle_generation_seeded()

    assert reads["n"] == 1, f"soul map read {reads['n']} times for two seeds"
