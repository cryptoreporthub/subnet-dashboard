"""A failed membership read must not pin an aged-negative netuid after the source recovers.

Issue #1510. Behavior tests through SnapshotBuilder and SubnetUniverseProvider.refresh_once.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from internal.subnet_universe import (
    STALE_GRACE_SECONDS,
    SnapshotBuilder,
    SubnetUniverseProvider,
    UniverseSnapshot,
    _reset_provider_for_tests,
    _validity_entry,
)

PHANTOM = 129
REGISTERED = (0, 1, 2, 5)
HEALTHY = ("ok", False, False)


@pytest.fixture(autouse=True)
def _provider_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    monkeypatch.setenv("RUN_MODE", "worker")
    _reset_provider_for_tests()
    yield
    _reset_provider_for_tests()


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _health(snap: UniverseSnapshot):
    return (snap.status, snap.degraded, snap.refresh_incomplete)


def _snapshot(negative_since: str, *, stamped: bool = False) -> UniverseSnapshot:
    netuids = tuple(sorted((*REGISTERED, PHANTOM)))
    validity = {
        str(n): _validity_entry(validity="positive", sources=["taomarketcap", "blockmachine_probe"])
        for n in REGISTERED
    }
    validity[str(PHANTOM)] = _validity_entry(
        validity="negative",
        sources=[],
        negative_since=negative_since,
        refresh_incomplete=stamped,
    )
    return UniverseSnapshot(
        netuids=netuids,
        rows=tuple({"netuid": n, "name": f"SN{n}"} for n in netuids),
        resolved_at=_ago(0),
        status="ok",
        degraded=False,
        validity_map=validity,
    )


def _tmc():
    return set(REGISTERED), {n: {"netuid": n, "name": f"SN{n}"} for n in REGISTERED}, True


def _clean_read(netuids, deadline):
    return {**{n: True for n in REGISTERED if n != 0}, 0: True, PHANTOM: False}, True


def _failed_read(netuids, deadline):
    return {}, False


def _provider(tmp_path, snap, *, persist=False):
    provider = SubnetUniverseProvider(persist_file=str(tmp_path / "subnet_universe.json"))
    provider.replace_snapshot_for_tests(snap, persist=persist)
    return provider


def _cycle(provider, probe, tmc=_tmc):
    provider.set_builder(SnapshotBuilder(tmc_fetch=tmc, probe_fetch=probe))
    return provider.refresh_once()


def test_clean_read_removes_aged_negative_baseline(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS + 60)))
    result = _cycle(provider, _clean_read)
    assert PHANTOM not in result.netuids
    assert _health(result) == HEALTHY


def test_failed_cycle_removes_nothing_and_stays_incomplete(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS + 60)))
    result = _cycle(provider, _failed_read)
    assert set(result.netuids) == {*REGISTERED, PHANTOM}
    assert result.validity_map[str(PHANTOM)]["refresh_incomplete"] is True
    assert result.refresh_incomplete is True


def test_failed_read_after_grace_then_clean_read_removes_phantom(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS + 60)))
    _cycle(provider, _failed_read)
    result = _cycle(provider, _clean_read)
    assert PHANTOM not in result.netuids
    assert PHANTOM not in provider.get_snapshot().netuids
    assert _health(result) == HEALTHY


def test_failed_read_inside_grace_then_clean_read_after_grace_removes_phantom(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS - 3600)))
    _cycle(provider, _failed_read)
    aged = provider.get_snapshot()
    entry = dict(aged.validity_map[str(PHANTOM)], negative_since=_ago(STALE_GRACE_SECONDS + 60))
    provider.replace_snapshot_for_tests(replace(aged, validity_map={**aged.validity_map, str(PHANTOM): entry}))
    result = _cycle(provider, _clean_read)
    assert PHANTOM not in result.netuids
    assert _health(result) == HEALTHY


def test_snapshot_carrying_stale_stamp_in_memory_converges(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS + 60), stamped=True))
    result = _cycle(provider, _clean_read)
    assert PHANTOM not in result.netuids
    assert _health(result) == HEALTHY


def test_stale_stamp_survives_disk_round_trip_and_restart_then_converges(tmp_path):
    path = str(tmp_path / "subnet_universe.json")
    writer = SubnetUniverseProvider(persist_file=path)
    writer.replace_snapshot_for_tests(_snapshot(_ago(STALE_GRACE_SECONDS + 60)), persist=True)
    _cycle(writer, _failed_read)

    _reset_provider_for_tests()
    restarted = SubnetUniverseProvider(persist_file=path)
    assert restarted.get_snapshot().validity_map[str(PHANTOM)]["refresh_incomplete"] is True

    result = _cycle(restarted, _clean_read)
    assert PHANTOM not in result.netuids
    assert _health(result) == HEALTHY


def test_registered_netuids_survive_every_cycle(tmp_path):
    provider = _provider(tmp_path, _snapshot(_ago(STALE_GRACE_SECONDS + 60)))
    for probe in (_failed_read, _clean_read, _clean_read):
        result = _cycle(provider, probe)
        assert set(REGISTERED) <= set(result.netuids)


def test_root_is_never_removed_even_when_both_sources_say_false(tmp_path):
    snap = _snapshot(_ago(STALE_GRACE_SECONDS + 60))
    validity = dict(snap.validity_map)
    validity["0"] = _validity_entry(validity="negative", sources=[], negative_since=_ago(STALE_GRACE_SECONDS + 60))
    provider = _provider(tmp_path, replace(snap, validity_map=validity))

    def tmc_without_root():
        ids = set(REGISTERED) - {0}
        return ids, {n: {"netuid": n, "name": f"SN{n}"} for n in ids}, True

    def probe_root_false(netuids, deadline):
        return {1: True, 2: True, 5: True, 0: False, PHANTOM: False}, True

    result = _cycle(provider, probe_root_false, tmc=tmc_without_root)
    assert 0 in result.netuids


def test_swap_that_drops_an_in_grace_netuid_is_refused(tmp_path):
    prior = _snapshot(_ago(STALE_GRACE_SECONDS - 3600))
    provider = _provider(tmp_path, prior)

    class _SwapBuilder:
        def build(self, snapshot):
            kept = tuple(n for n in snapshot.netuids if n != PHANTOM) + (200,)
            return replace(snapshot, netuids=tuple(sorted(kept)))

    provider.set_builder(_SwapBuilder())
    result = provider.refresh_once()
    assert PHANTOM in result.netuids
    assert 200 not in result.netuids
    assert _health(result) == ("degraded", True, True)


def test_ghost_validity_key_does_not_reenter_after_a_failed_probe(tmp_path):
    snap = _snapshot(_ago(STALE_GRACE_SECONDS + 60))
    members = tuple(n for n in snap.netuids if n != PHANTOM)
    ghost = replace(snap, netuids=members, rows=tuple(r for r in snap.rows if r["netuid"] != PHANTOM))
    provider = _provider(tmp_path, ghost)
    result = _cycle(provider, _failed_read)
    assert PHANTOM not in result.netuids


def test_member_missing_from_validity_map_is_unobserved_not_positive(tmp_path):
    snap = _snapshot(_ago(STALE_GRACE_SECONDS + 60))
    validity = {k: v for k, v in snap.validity_map.items() if k != "5"}
    provider = _provider(tmp_path, replace(snap, validity_map=validity))
    def tmc_without_five():
        ids = set(REGISTERED) - {5}
        return ids, {n: {"netuid": n, "name": f"SN{n}"} for n in ids}, True

    result = _cycle(provider, _failed_read, tmc=tmc_without_five)
    assert 5 in result.netuids
    assert result.validity_map["5"]["validity"] == "unobserved"
    assert result.validity_map["5"]["refresh_incomplete"] is True


def test_removing_every_member_in_one_cycle_is_published(tmp_path):
    old = _ago(STALE_GRACE_SECONDS + 60)
    validity = {str(n): _validity_entry(validity="negative", sources=[], negative_since=old) for n in (130, 131)}
    prior = UniverseSnapshot(
        netuids=(130, 131),
        rows=tuple({"netuid": n, "name": f"SN{n}"} for n in (130, 131)),
        resolved_at=_ago(0),
        status="ok",
        degraded=False,
        validity_map=validity,
    )
    provider = _provider(tmp_path, prior)

    def tmc_empty():
        return set(), {}, True

    def probe_all_false(netuids, deadline):
        return {130: False, 131: False}, True

    result = _cycle(provider, probe_all_false, tmc=tmc_empty)
    assert not ({130, 131} & set(result.netuids))
