import json
from pathlib import Path

from internal.chain_read import ChainRead
from internal.council.seed_quality import validate_shipped_seed

REPO = Path(__file__).resolve().parents[1]


def _seed() -> dict:
    return json.loads((REPO / "data_seeds" / "score_snapshots.json").read_text(encoding="utf-8"))


def test_committed_seed_carries_a_parseable_chain_read():
    chain = ChainRead.parse(_seed()["coverage"]["membership"].get("chain"))
    assert chain is not None


def test_committed_seed_rows_are_exactly_its_chain_read():
    seed = _seed()
    chain = ChainRead.parse(seed["coverage"]["membership"].get("chain"))
    assert chain is not None
    day_ids = [row["netuid"] for row in seed["day"]]
    assert sorted(day_ids) == list(chain.netuids)
    assert seed["coverage"]["membership"]["expected_netuids"] == list(chain.netuids)


def test_committed_seed_passes_the_shipped_seed_gate():
    ok, reason = validate_shipped_seed(_seed())
    assert ok, reason
