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
