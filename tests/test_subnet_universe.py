"""D5 subnet universe tests T1–T9."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from internal.subnet_universe import (
    MAX_NETUIDS,
    STALE_GRACE_SECONDS,
    SnapshotBuilder,
    SubnetUniverseProvider,
    UniverseSnapshot,
    _reset_provider_for_tests,
    _validity_entry,
    get_lkg_or_emergency,
    get_provider,
    persist_path,
)


@pytest.fixture(autouse=True)
def _reset_universe_provider():
    _reset_provider_for_tests()
    yield
    _reset_provider_for_tests()


@pytest.fixture
def universe_tmp(tmp_path, monkeypatch):
    path = tmp_path / "subnet_universe.json"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return path


def _prior_snapshot(netuids: list[int]) -> UniverseSnapshot:
    rows = tuple({"netuid": n, "name": f"SN{n}"} for n in netuids)
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in netuids}
    return UniverseSnapshot(
        netuids=tuple(netuids),
        rows=rows,
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map=validity,
    )


def test_t1_empty_state_emergency_registry(universe_tmp):
  """Cold boot with no disk file serves emergency_registry."""
  provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
  snap = provider.get_snapshot()
  assert snap.status == "emergency_registry"
  assert snap.degraded is True
  assert len(snap.netuids) > 0
  emergency = provider.get_lkg_or_emergency()
  assert emergency.status == "emergency_registry"

  built = SnapshotBuilder(
      tmc_fetch=lambda: ({1, 2, 3}, {1: {"netuid": 1}, 2: {"netuid": 2}, 3: {"netuid": 3}}, True),
      probe_fetch=lambda netuids, deadline: ({n: True for n in netuids}, True),
  ).build(None)
  assert built.status == "ok"
  assert list(built.netuids) == [1, 2, 3]


def test_t2_shrink_regression_blocked(universe_tmp):
  """Refresh must not shrink 120 -> 75 when sources clip."""
  prior = _prior_snapshot(list(range(120)))
  builder = SnapshotBuilder(
      tmc_fetch=lambda: (set(range(75)), {}, True),
      probe_fetch=lambda netuids, deadline: ({n: False for n in netuids}, True),
  )
  provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
  provider.replace_snapshot_for_tests(prior)
  provider.set_builder(builder)
  result = provider.refresh_once()
  assert len(result.netuids) == 120
  assert result.status in ("degraded", "ok")


def test_t3_source_failure_serves_lkg_not_registry_only(universe_tmp):
  """Source failure retains full LKG universe, not 75-row registry clip."""
  prior = _prior_snapshot(list(range(100, 160)))
  provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
  provider.replace_snapshot_for_tests(prior, persist=True)
  provider.set_builder(
      SnapshotBuilder(
          tmc_fetch=lambda: (set(), {}, False),
          probe_fetch=lambda netuids, deadline: ({}, False),
      )
  )
  refreshed = provider.refresh_once()
  assert len(refreshed.netuids) == 60
  assert refreshed.degraded is True
  lkg = provider.get_lkg_or_emergency()
  assert len(lkg.netuids) == 60
  assert lkg.status != "emergency_registry"


def test_t4_cap_at_max_netuids(universe_tmp):
  """Builder stops at MAX_NETUIDS=200 with cap_reached."""
  big = list(range(250))
  builder = SnapshotBuilder(
      tmc_fetch=lambda: (set(big), {n: {"netuid": n} for n in big}, True),
      probe_fetch=lambda netuids, deadline: ({n: True for n in netuids}, True),
  )
  built = builder.build(None)
  assert len(built.netuids) == MAX_NETUIDS
  assert built.cap_reached is True


def test_t5_corrupt_persistence_emergency_registry(universe_tmp, caplog):
  """Invalid JSON on disk -> emergency_registry without crash."""
  universe_tmp.write_text("{not-json", encoding="utf-8")
  provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
  snap = provider.get_snapshot()
  assert snap.status == "emergency_registry"
  good = _prior_snapshot([1, 2, 3])
  provider.replace_snapshot_for_tests(good, persist=True)
  with open(universe_tmp, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
  assert len(payload["netuids"]) == 3


def test_t6_concurrent_reads_during_write(universe_tmp):
  """Readers never observe torn snapshots during publish."""
  provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
  provider.replace_snapshot_for_tests(_prior_snapshot([1, 2, 3]))
  errors: list[str] = []
  stop = threading.Event()

  def reader() -> None:
      while not stop.is_set():
          snap = provider.get_snapshot()
          netuids = list(snap.netuids)
          if netuids != sorted(netuids):
              errors.append(f"unsorted: {netuids}")
          if len(set(netuids)) != len(netuids):
              errors.append(f"dupes: {netuids}")

  threads = [threading.Thread(target=reader) for _ in range(8)]
  for thread in threads:
      thread.start()
  for idx in range(20):
      provider.replace_snapshot_for_tests(_prior_snapshot(list(range(idx, idx + 5))))
  stop.set()
  for thread in threads:
      thread.join(timeout=2)
  assert not errors


def test_t7_api_sort_filter_compat():
  """_apply_subnets_query sort/filter unchanged apart from membership count."""
  from starlette.requests import Request

  from server import _apply_subnets_query

  base = {
      "items": [{"id": n, "netuid": n, "emission": n * 10, "status": "active"} for n in range(5)],
      "feed_meta": {"source": "blockmachine", "sources": ["blockmachine"], "universe_status": "ok"},
  }
  scope = {
      "type": "http",
      "method": "GET",
      "path": "/api/subnets",
      "headers": [],
      "query_string": b"sort=emission&order=desc&limit=2&offset=1",
  }
  request = Request(scope)
  out = _apply_subnets_query(base, request)
  assert out["meta"]["total"] == 5
  assert out["meta"]["universe_status"] == "ok"
  assert [row["netuid"] for row in out["subnets"]] == [3, 2]


def test_t8_partial_refresh_does_not_start_removal_clock(universe_tmp):
  """Timeout/incomplete refresh must not mark unobserved members invalid."""
  prior = _prior_snapshot([10, 11, 12])
  builder = SnapshotBuilder(
      tmc_fetch=lambda: (set(), {}, False),
      probe_fetch=lambda netuids, deadline: ({10: None, 11: None, 12: None}, False),
  )
  built = builder.build(prior)
  assert built.refresh_incomplete is True
  for netuid in (10, 11, 12):
      entry = built.validity_map[str(netuid)]
      assert entry["validity"] in ("positive", "unobserved")
      assert entry.get("negative_since") in (None, "")


def test_t9_source_disagreement_retains_member(universe_tmp):
  """Conflicting sources retain member with disputed=true."""
  prior = _prior_snapshot([42])
  builder = SnapshotBuilder(
      tmc_fetch=lambda: ({42}, {42: {"netuid": 42}}, True),
      probe_fetch=lambda netuids, deadline: ({42: False}, True),
  )
  built = builder.build(prior)
  assert 42 in built.netuids
  entry = built.validity_map["42"]
  assert entry["disputed"] is True
  assert entry["validity"] == "positive"


def test_negative_validity_removal_after_grace(universe_tmp):
    """Continuous negative validity removes member only after 48h grace."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=STALE_GRACE_SECONDS + 60)).isoformat()
    prior = UniverseSnapshot(
        netuids=(99,),
        rows=({"netuid": 99, "name": "SN99"},),
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map={
            "99": _validity_entry(
                validity="negative",
                sources=["taomarketcap", "blockmachine_probe"],
                negative_since=old,
            )
        },
    )
    builder = SnapshotBuilder(
        tmc_fetch=lambda: (set(), {}, True),
        probe_fetch=lambda netuids, deadline: ({99: False}, True),
    )
    built = builder.build(prior)
    assert 99 not in built.netuids


def test_provider_grace_removal_via_refresh_once(universe_tmp, monkeypatch):
    """Provider.refresh_once() must publish grace-eligible removals."""
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    monkeypatch.setenv("RUN_MODE", "worker")
    old = (datetime.now(timezone.utc) - timedelta(seconds=STALE_GRACE_SECONDS + 60)).isoformat()
    prior = UniverseSnapshot(
        netuids=(99, 100),
        rows=(
            {"netuid": 99, "name": "SN99"},
            {"netuid": 100, "name": "SN100"},
        ),
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map={
            "99": _validity_entry(
                validity="negative",
                sources=["taomarketcap"],
                negative_since=old,
            ),
            "100": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    )
    builder = SnapshotBuilder(
        tmc_fetch=lambda: ({100}, {100: {"netuid": 100, "name": "SN100"}}, True),
        probe_fetch=lambda netuids, deadline: ({99: False, 100: True}, True),
    )
    provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
    provider.replace_snapshot_for_tests(prior)
    provider.set_builder(builder)
    result = provider.refresh_once()
    assert 99 not in result.netuids
    assert 100 in result.netuids
    assert provider.get_snapshot().netuids == result.netuids


def test_web_reader_does_not_publish_refresh(universe_tmp, monkeypatch):
    """Web process reloads disk only — refresh_once must not run builder publish."""
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    monkeypatch.setenv("RUN_MODE", "web")
    prior = _prior_snapshot([1, 2, 3])
    provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
    provider.replace_snapshot_for_tests(prior, persist=True)
    provider.set_builder(
        SnapshotBuilder(
            tmc_fetch=lambda: (set(range(75)), {}, True),
            probe_fetch=lambda netuids, deadline: ({n: False for n in netuids}, True),
        )
    )
    result = provider.refresh_once()
    assert list(result.netuids) == [1, 2, 3]


def test_web_reader_reload_picks_worker_snapshot(universe_tmp, monkeypatch):
    """Worker publishes snapshot file; web reader reloads without writing."""
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    path = str(universe_tmp)
    monkeypatch.setenv("RUN_MODE", "web")
    reader = SubnetUniverseProvider(persist_file=path)

    monkeypatch.setenv("RUN_MODE", "worker")
    writer = SubnetUniverseProvider(persist_file=path)
    writer.replace_snapshot_for_tests(_prior_snapshot([10, 11, 12]), persist=True)

    monkeypatch.setenv("RUN_MODE", "web")
    reloaded = reader.reload_from_disk_if_stale()
    assert list(reloaded.netuids) == [10, 11, 12]


def test_get_lkg_or_emergency_uses_provider_singleton(universe_tmp):
    provider = get_provider()
    provider.replace_snapshot_for_tests(_prior_snapshot([7, 8, 9]))
    snap = get_lkg_or_emergency()
    assert list(snap.netuids) == [7, 8, 9]


def test_cold_start_empty_tmc_emergency_registry(universe_tmp):
    """No prior snapshot + empty successful TMC => emergency_registry, never zero-member ok."""
    built = SnapshotBuilder(
        tmc_fetch=lambda: (set(), {}, True),
        probe_fetch=lambda netuids, deadline: ({}, True),
    ).build(None)
    assert built.status == "emergency_registry"
    assert len(built.netuids) > 0
    assert built.degraded is True


def test_cold_start_empty_tmc_emergency_registry_via_provider(universe_tmp, monkeypatch):
    """Provider on cold start must not publish zero-member ok snapshot."""
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    monkeypatch.setenv("RUN_MODE", "worker")
    provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
    assert provider.get_snapshot().status == "emergency_registry"
    provider.set_builder(
        SnapshotBuilder(
            tmc_fetch=lambda: (set(), {}, True),
            probe_fetch=lambda netuids, deadline: ({}, True),
        )
    )
    result = provider.refresh_once()
    assert len(result.netuids) > 0
    assert result.degraded is True
    assert result.status != "ok"


def test_lkg_empty_tmc_retains_full_snapshot_via_provider(universe_tmp, monkeypatch):
    """Existing LKG + empty successful TMC must not publish zero-member ok snapshot."""
    monkeypatch.setattr("internal.subnet_universe._ci_or_test", lambda: False)
    monkeypatch.setenv("RUN_MODE", "worker")
    prior = UniverseSnapshot(
        netuids=tuple(range(100, 160)),
        rows=tuple({"netuid": n, "name": f"SN{n}"} for n in range(100, 160)),
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map={},
    )
    provider = SubnetUniverseProvider(persist_file=str(universe_tmp))
    provider.replace_snapshot_for_tests(prior, persist=True)
    provider.set_builder(
        SnapshotBuilder(
            tmc_fetch=lambda: (set(), {}, True),
            probe_fetch=lambda netuids, deadline: ({}, True),
        )
    )
    result = provider.refresh_once()
    assert len(result.netuids) == 60
    assert result.degraded is True
    assert result.status == "degraded"
    assert provider.get_snapshot().netuids == prior.netuids
