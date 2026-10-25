import json
import tempfile

import pytest

from internal.council.build_seed_snapshot import build_image_seed_snapshot
from internal.council.seed_market_inputs import build_authoritative_hydrate_rows
from internal.council.seed_quality import validate_shipped_seed
from tests.score_snapshot_testutil import chain_read

COMMITTED_IDS = tuple(range(1, 129))


def test_hydrate_rows_are_exactly_the_requested_chain_ids():
    rows, prov = build_authoritative_hydrate_rows((1, 2, 5))
    assert [row["netuid"] for row in rows] == [1, 2, 5]
    assert prov["netuid_count"] == prov["hydrate_row_count"] == 3
    for row in rows:
        assert "Alpha Subnet" not in row["name"]
        assert row["price"] > 0


def test_a_chain_id_with_no_market_row_fails_loudly_by_name():
    with pytest.raises(ValueError, match="9999"):
        build_authoritative_hydrate_rows((1, 2, 9999))


def test_seed_build_publishes_the_chain_read_it_was_given():
    chain = chain_read(COMMITTED_IDS)
    with tempfile.TemporaryDirectory() as tmp:
        volume = f"{tmp}/vol.json"
        out = build_image_seed_snapshot(chain=chain, volume_path=volume, cycle_path=f"{tmp}/cycle.json")
        assert out.get("published")
        snap = json.loads(open(volume, encoding="utf-8").read())
    assert snap["coverage"]["membership"]["chain"] == chain.to_dict()
    assert snap["coverage"]["membership"]["expected_netuids"] == list(chain.netuids)
    assert sorted(row["netuid"] for row in snap["day"]) == list(chain.netuids)
    ok, reason = validate_shipped_seed(snap)
    assert ok, reason
    assert snap["build_provenance"]["market_inputs"]["universe_sha256"]


def test_seed_build_refuses_a_chain_id_it_has_no_market_data_for():
    chain = chain_read(COMMITTED_IDS + (4000,))
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="4000"):
            build_image_seed_snapshot(
                chain=chain, volume_path=f"{tmp}/vol.json", cycle_path=f"{tmp}/cycle.json"
            )


def _live_inputs(tmp_path, *, price, close, volume=1.0):
    universe = tmp_path / "universe.json"
    universe.write_text(
        json.dumps({"rows": [{"netuid": 7, "name": "Seven", "price": price, "volume": volume}]}),
        encoding="utf-8",
    )
    cache = tmp_path / "price_cache.json"
    cache.write_text(json.dumps({"7": {"candles": [{"close": close}]}}), encoding="utf-8")
    return {"universe_path": universe, "registry_path": tmp_path / "none.json", "price_cache_path": cache}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "inf"])
def test_a_non_finite_price_is_missing_so_the_cache_close_is_used(tmp_path, bad):
    rows, _ = build_authoritative_hydrate_rows((7,), **_live_inputs(tmp_path, price=bad, close=2.5))
    assert rows[0]["price"] == 2.5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_price_and_cache_close_fails_loudly_by_netuid(tmp_path, bad):
    with pytest.raises(ValueError, match="7"):
        build_authoritative_hydrate_rows((7,), **_live_inputs(tmp_path, price=bad, close=bad))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_missing_price_with_a_non_finite_cache_close_fails_loudly(tmp_path, bad):
    with pytest.raises(ValueError, match="7"):
        build_authoritative_hydrate_rows((7,), **_live_inputs(tmp_path, price=None, close=bad))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_volume_is_treated_as_missing(tmp_path, bad):
    rows, _ = build_authoritative_hydrate_rows((7,), **_live_inputs(tmp_path, price=1.0, close=1.0, volume=bad))
    assert rows[0]["volume"] == 0.0


@pytest.mark.parametrize("field", ["price", "volume"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_committed_row_with_a_non_finite_value_is_refused(tmp_path, field, bad):
    from internal.council.seed_market_inputs import _committed_rows_for

    row = {"netuid": 7, "name": "Seven", "price": 1.0, "volume": 1.0, "source": "x"}
    row[field] = bad
    committed = tmp_path / "rows.json"
    committed.write_text(json.dumps({"rows": [row], "market_inputs": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="7"):
        _committed_rows_for(committed, (7,))
