"""Drive real score-snapshot writer/reader paths for #1479 invariant sequences."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pytest

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.subnet_universe import UniverseSnapshot, _validity_entry
from tests.score_snapshot_testutil import complete_snapshot_payload

EVENTS: List[str] = [
    "complete_build",
    "partial_build",
    "capped_build",
    "capture_timeout",
    "gated_cycle",
    "chain_read_failure",
    "crash_mid_write",
    "restart",
    "age_past_alert",
    "first_boot",
    "corrupt_volume_file",
    "legacy_partial_on_volume",
]

STARTS: List[str] = ["complete_on_volume", "first_boot_with_seed"]


def _membership_ok(*, gated: bool = False) -> UniverseSnapshot:
    from datetime import datetime, timezone

    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return UniverseSnapshot(
        netuids=(1, 2, 3),
        rows=(
            {"netuid": 1, "name": "A", "price": 1.0, "volume": 1000.0, "source": "taomarketcap"},
            {"netuid": 2, "name": "B", "price": 1.0, "volume": 1000.0, "source": "taomarketcap"},
            {"netuid": 3, "name": "C", "price": 1.0, "volume": 1000.0, "source": "taomarketcap"},
        ),
        resolved_at=resolved,
        status="ok",
        degraded=gated,
        cap_reached=gated,
        refresh_incomplete=gated,
        validity_map={
            "1": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "2": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "3": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    )


@dataclass
class InvariantWorld:
    tmp_path: Any
    monkeypatch: pytest.MonkeyPatch
    volume_path: str = ""
    seed_path: str = ""
    cycle_path: str = ""
    _real_json_dump: Any = field(default=None, repr=False)
    _allow_none: bool = False

    def setup_paths(self) -> None:
        self.volume_path = str(self.tmp_path / "volume.json")
        self.seed_path = str(self.tmp_path / "seed.json")
        self.cycle_path = str(self.tmp_path / "cycle.json")
        self.monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", self.volume_path)
        self.monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", self.seed_path)
        self.monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", self.cycle_path)
        self.monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
        self.monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
        hydrate = [
            {"netuid": n, "name": f"S{n}", "price": 1.0, "volume": 1000.0}
            for n in (1, 2, 3)
        ]
        self.monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
        self.monkeypatch.setattr(
            "internal.subnet_universe.get_snapshot",
            lambda: _membership_ok(gated=False),
        )
        self.monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS", 0)

    def start(self, name: str) -> None:
        self.setup_paths()
        seed = complete_snapshot_payload(
            day_rows=[{"netuid": n, "total_score": float(n)} for n in (1, 2, 3)],
        )
        with open(self.seed_path, "w", encoding="utf-8") as handle:
            json.dump(seed, handle)
        if name == "complete_on_volume":
            snaps.save_score_snapshot(seed, self.volume_path)
            self._allow_none = False
        elif name == "first_boot_with_seed":
            self._allow_none = False
        else:
            raise ValueError(name)

    def _wire_day_scorer(self, fn: Callable) -> None:
        self.monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", fn)
        self.monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", fn)

    def apply(self, event: str) -> None:
        if event == "complete_build":
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": float(sn["netuid"])})
            snaps.write_full_universe_snapshot()
        elif event == "partial_build":
            def _day(sn, _ctx):
                if int(sn["netuid"]) == 3:
                    raise RuntimeError("score fail")
                return {"total_score": float(sn["netuid"])}

            self._wire_day_scorer(_day)
            snaps.write_full_universe_snapshot()
        elif event == "capped_build":
            self.monkeypatch.setattr(
                "internal.subnet_universe.get_snapshot",
                lambda: _membership_ok(gated=False),
            )
            self.monkeypatch.setattr(
                "server._get_subnets_hydrate",
                lambda: ([{"netuid": 1, "name": "A", "price": 1.0, "volume": 1000.0}], "registry-fallback"),
            )
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": 1.0})
            snaps.write_full_universe_snapshot()
        elif event == "capture_timeout":
            self.monkeypatch.setattr(cov, "coverage_capture_deadline_seconds", lambda _s: False)
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": float(sn["netuid"])})
            snaps.write_full_universe_snapshot()
            self.monkeypatch.setattr(cov, "coverage_capture_deadline_seconds", cov.coverage_capture_deadline_seconds)
        elif event == "gated_cycle":
            self.monkeypatch.setattr(
                "internal.subnet_universe.get_snapshot",
                lambda: _membership_ok(gated=True),
            )
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": float(sn["netuid"])})
            snaps.write_full_universe_snapshot()
            self.monkeypatch.setattr(
                "internal.subnet_universe.get_snapshot",
                lambda: _membership_ok(gated=False),
            )
        elif event == "chain_read_failure":
            self.monkeypatch.setattr(
                "internal.council.snapshot_coverage.load_membership_receipt",
                lambda: {
                    "expected_netuids": [],
                    "fresh": False,
                    "degraded": True,
                    "cap_reached": False,
                    "refresh_incomplete": True,
                },
            )
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": 1.0})
            snaps.write_full_universe_snapshot()
        elif event == "crash_mid_write":
            real_dump = json.dump
            self._real_json_dump = real_dump

            def _boom(obj, fp, *args, **kwargs):
                if getattr(fp, "name", "").endswith(".tmp"):
                    real_dump({"partial": True}, fp, *args, **kwargs)
                    raise OSError("crash mid-write")
                return real_dump(obj, fp, *args, **kwargs)

            self.monkeypatch.setattr(json, "dump", _boom)
            self._wire_day_scorer(lambda sn, _ctx: {"total_score": float(sn["netuid"])})
            try:
                snaps.write_full_universe_snapshot()
            except OSError:
                pass
            self.monkeypatch.setattr(json, "dump", real_dump)
        elif event == "restart":
            snaps._served_parse_cache.clear()
        elif event == "age_past_alert":
            served = snaps.read_served_snapshot()
            if served.servable and served.snapshot:
                old = complete_snapshot_payload(
                    day_rows=served.snapshot.get("day") or [{"netuid": 1, "total_score": 1.0}],
                    written_at="2018-01-01T00:00:00Z",
                )
                with open(self.volume_path, "w", encoding="utf-8") as handle:
                    json.dump(old, handle)
        elif event == "first_boot":
            try:
                import os

                os.unlink(self.volume_path)
            except OSError:
                pass
            self._allow_none = True
        elif event == "corrupt_volume_file":
            with open(self.volume_path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")
        elif event == "legacy_partial_on_volume":
            with open(self.volume_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "written_at": snaps._now_iso(),
                        "coverage": {"complete": False},
                        "day": [{"netuid": 9, "total_score": 1.0}],
                        "hour": [],
                    },
                    handle,
                )
        else:
            raise ValueError(event)
        self._allow_none = False

    def assert_invariant(self) -> None:
        served = snaps.read_served_snapshot()
        if not served.servable:
            if self._allow_none:
                return
            pytest.fail(f"unservable state {served.state} reason={served.reason}")
        assert snaps.is_complete_snapshot(served.snapshot)
        picks = snaps.build_top_picks_from_snapshot(None)
        assert picks is not None
        assert picks.get("day_picks"), "day_picks must be non-empty"
        if served.origin == "volume":
            on_disk = snaps.load_score_snapshot(self.volume_path)
            if on_disk is not None:
                assert snaps.is_complete_snapshot(on_disk), "volume must not hold partial"


def pair_cases() -> List[tuple[str, str, str]]:
    out: List[tuple[str, str, str]] = []
    for start in STARTS:
        for e1 in EVENTS:
            for e2 in EVENTS:
                out.append((start, e1, e2))
    return out


def random_sequences(n: int = 25, seed: int = 1479) -> List[List[str]]:
    rng = random.Random(seed)
    return [rng.sample(EVENTS, k=min(12, len(EVENTS))) for _ in range(n)]
