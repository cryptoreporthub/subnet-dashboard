from __future__ import annotations

from datetime import datetime, timezone

import pytest

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.subnet_universe import UniverseSnapshot, _validity_entry

ACTIVE = tuple(range(1, 129))
PLACEHOLDERS = tuple(range(129, 166))


@pytest.fixture(autouse=True)
def _reset_phase1_state():
    cov.reset_phase1_cycle_state_for_tests()
    yield
    cov.reset_phase1_cycle_state_for_tests()


def _active_row(n):
    return {"netuid": n, "id": n, "name": f"S{n}", "source": "taomarketcap", "sources": ["taomarketcap"]}


def _placeholder_row(n):
    return {"netuid": n, "id": n, "source": "none", "sources": ["none"]}


def _deregistered():
    return _validity_entry(validity="negative", negative_since="2026-10-20T00:00:00+00:00")


def _membership(active=ACTIVE, placeholders=PLACEHOLDERS, placeholder_validity=_deregistered) -> UniverseSnapshot:
    netuids = tuple(sorted(active + placeholders))
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in active}
    validity.update({str(n): placeholder_validity() for n in placeholders})
    return UniverseSnapshot(
        netuids=netuids,
        rows=tuple(_active_row(n) for n in active) + tuple(_placeholder_row(n) for n in placeholders),
        resolved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status="ok",
        degraded=False,
        validity_map=validity,
    )


def _build(tmp_path, monkeypatch, membership, hydrate_rows):
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: membership)

    def _score(sn, _ctx):
        return {"total_score": 44.44 if sn.get("source") == "none" else 60.0 + int(sn["netuid"]) / 10}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _score)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _score)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate_rows, "taomarketcap"))
    return snaps.write_full_universe_snapshot()


@pytest.mark.parametrize("feed_has_placeholders", [True, False])
def test_snapshot_is_complete_over_the_active_subnets(tmp_path, monkeypatch, feed_has_placeholders):
    hydrate = [_active_row(n) for n in ACTIVE]
    if feed_has_placeholders:
        hydrate += [_placeholder_row(n) for n in PLACEHOLDERS]
    out = _build(tmp_path, monkeypatch, _membership(), hydrate)
    coverage = out["coverage"]
    assert coverage["complete"] is True
    assert coverage["day"]["missing_not_admitted"] == []
    assert len(coverage["day"]["expected"]) == len(ACTIVE)
    saved = snaps.load_score_snapshot(str(tmp_path / "score_snapshots.json"))
    assert sorted(r["netuid"] for r in saved["day"]) == list(ACTIVE)


def test_placeholder_slots_are_never_scored_or_served(tmp_path, monkeypatch):
    hydrate = [_active_row(n) for n in ACTIVE] + [_placeholder_row(n) for n in PLACEHOLDERS]
    _build(tmp_path, monkeypatch, _membership(), hydrate)
    path = str(tmp_path / "score_snapshots.json")
    picks = snaps.build_top_picks_from_snapshot(hydrate, path=path, max_age_seconds=7200)
    assert picks is not None
    served = {p["netuid"] for p in picks["day_picks"] + picks["hour_picks"]}
    assert served and served.isdisjoint(PLACEHOLDERS)
    scored = {r["netuid"] for r in snaps.load_score_snapshot(path)["day"]}
    assert scored.isdisjoint(PLACEHOLDERS)


def test_membership_with_no_active_subnet_is_not_complete(tmp_path, monkeypatch):
    membership = _membership(active=(), placeholders=PLACEHOLDERS)
    hydrate = [_placeholder_row(n) for n in PLACEHOLDERS]
    out = _build(tmp_path, monkeypatch, membership, hydrate)
    assert out["coverage"]["complete"] is False


def test_receipt_expects_the_subnets_that_have_data():
    import internal.subnet_universe as universe

    original = universe.get_snapshot
    universe.get_snapshot = lambda: _membership()
    try:
        receipt = cov.load_membership_receipt()
    finally:
        universe.get_snapshot = original
    assert receipt["expected_netuids"] == list(ACTIVE)
    assert receipt["inactive_netuids"] == list(PLACEHOLDERS)


def _receipt_for(membership):
    import internal.subnet_universe as universe

    original = universe.get_snapshot
    universe.get_snapshot = lambda: membership
    try:
        return cov.load_membership_receipt()
    finally:
        universe.get_snapshot = original


@pytest.mark.parametrize(
    "validity",
    [
        lambda: _validity_entry(validity="positive", sources=["blockmachine_probe"], disputed=True),
        lambda: _validity_entry(validity="positive", sources=["taomarketcap"], refresh_incomplete=True),
        lambda: _validity_entry(validity="unobserved", refresh_incomplete=True),
    ],
    ids=["probe_positive", "retained_positive", "unobserved"],
)
def test_a_member_without_row_data_stays_expected_unless_established_inactive(validity):
    receipt = _receipt_for(_membership(placeholders=PLACEHOLDERS, placeholder_validity=validity))
    assert receipt["expected_netuids"] == sorted(ACTIVE + PLACEHOLDERS)
    assert receipt["inactive_netuids"] == []


def test_a_member_with_no_validity_entry_stays_expected():
    membership = _membership()
    membership = UniverseSnapshot(
        netuids=membership.netuids,
        rows=membership.rows,
        resolved_at=membership.resolved_at,
        status="ok",
        degraded=False,
        validity_map={},
    )
    receipt = _receipt_for(membership)
    assert receipt["expected_netuids"] == sorted(ACTIVE + PLACEHOLDERS)


def test_a_negative_member_that_still_has_row_data_stays_expected():
    membership = _membership(active=ACTIVE, placeholders=())
    stale = tuple(ACTIVE[:3])
    validity = dict(membership.validity_map)
    validity.update({str(n): _deregistered() for n in stale})
    receipt = _receipt_for(
        UniverseSnapshot(
            netuids=membership.netuids,
            rows=membership.rows,
            resolved_at=membership.resolved_at,
            status="ok",
            degraded=False,
            validity_map=validity,
        )
    )
    assert receipt["expected_netuids"] == list(ACTIVE)
    assert receipt["inactive_netuids"] == []
