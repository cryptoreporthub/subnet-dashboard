import json
import os
import shutil

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import PINNED_HASH, chain_dict, complete_snapshot_payload

SEED = os.path.join("data_seeds", "score_snapshots.json")


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    if not os.path.isfile(SEED):
        pytest.skip("seed not generated in this checkout")
    shutil.copy(SEED, tmp_path / "seed.json")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))


def _payload(mutate=None, ids=(1,)):
    payload = complete_snapshot_payload(day_rows=[{"netuid": n, "total_score": 5.0} for n in ids])
    if mutate:
        mutate(payload)
    return payload


def _set_chain(payload, netuids, block_hash=PINNED_HASH):
    payload["coverage"]["membership"]["chain"] = {"block_hash": block_hash, "netuids": netuids}


CHAIN_AND_ROW_SHAPES = {
    "chain_missing": lambda p: p["coverage"]["membership"].pop("chain"),
    "chain_null": lambda p: p["coverage"]["membership"].update(chain=None),
    "chain_text": lambda p: p["coverage"]["membership"].update(chain="x"),
    "chain_empty": lambda p: _set_chain(p, []),
    "chain_short_hash": lambda p: _set_chain(p, [1], block_hash="0xabc"),
    "chain_unsorted": lambda p: (_set_chain(p, [2, 1]), p.update(day=[{"netuid": 1}, {"netuid": 2}])),
    "chain_null_id": lambda p: _set_chain(p, [None]),
    "chain_text_id": lambda p: _set_chain(p, ["abc"]),
    "chain_numeric_string_id": lambda p: _set_chain(p, ["1"]),
    "membership_not_a_dict": lambda p: p["coverage"].update(membership=[1]),
    "missing_row": lambda p: _set_chain(p, [1, 2]),
    "extra_row": lambda p: p.update(day=[{"netuid": 1}, {"netuid": 999}]),
    "duplicate_row": lambda p: p.update(day=[{"netuid": 1}, {"netuid": 1}]),
    "day_expected_junk_strings": lambda p: p["coverage"]["day"].update(expected=["bad"]),
    "day_expected_not_a_list": lambda p: p["coverage"]["day"].update(expected="bad"),
    "coverage_day_not_a_dict": lambda p: p["coverage"].update(day=["bad"]),
    "row_netuid_text": lambda p: p.update(day=[{"netuid": "x"}]),
    "row_netuid_numeric_string": lambda p: p.update(day=[{"netuid": "1"}]),
    "row_netuid_null": lambda p: p.update(day=[{"netuid": None}]),
    "row_without_netuid": lambda p: p.update(day=[{"netuid": 1}, {"total_score": 1.0}]),
    "row_not_a_dict": lambda p: p.update(day=[{"netuid": 1}, 7]),
    "day_not_a_list": lambda p: p.update(day=5),
    "day_empty": lambda p: p.update(day=[]),
    "hour_not_a_list": lambda p: p.update(hour=5),
    "hour_non_member": lambda p: p.update(hour=[{"netuid": 999}]),
    "hour_duplicate": lambda p: p.update(hour=[{"netuid": 1}, {"netuid": 1}]),
}

SCORER_SHAPES = {
    "revision_infinite": lambda p: p.update(scorer_revision=float("inf")),
    "revision_float": lambda p: p.update(scorer_revision=float(p["scorer_revision"])),
    "revision_text": lambda p: p.update(scorer_revision="1"),
    "revision_null": lambda p: p.update(scorer_revision=None),
    "digest_not_text": lambda p: p.update(scorer_digest=5),
    "digest_wrong": lambda p: p.update(scorer_digest="0" * 16),
}


@pytest.mark.parametrize("name", sorted({**CHAIN_AND_ROW_SHAPES, **SCORER_SHAPES}))
def test_a_malformed_volume_file_is_incomplete_and_the_seed_is_served(name, tmp_path):
    mutate = {**CHAIN_AND_ROW_SHAPES, **SCORER_SHAPES}[name]
    ids = (1, 2) if name == "chain_unsorted" else (1,)
    (tmp_path / "volume.json").write_text(json.dumps(_payload(mutate, ids)), encoding="utf-8")
    served = snaps.read_served_snapshot()
    assert served.state is snaps.ServedState.SEED
    picks = snaps.build_top_picks_from_snapshot(None)
    assert picks is not None and picks["day_picks"]


@pytest.mark.parametrize("name", sorted(CHAIN_AND_ROW_SHAPES))
def test_publish_refuses_a_malformed_snapshot_instead_of_raising(name):
    ids = (1, 2) if name == "chain_unsorted" else (1,)
    result = snaps.publish_complete_snapshot(_payload(CHAIN_AND_ROW_SHAPES[name], ids), snaps.SCORE_SNAPSHOTS_PATH)
    assert result.get("published") is False
    assert result.get("refused") == "incomplete"


def test_a_well_formed_snapshot_is_complete():
    assert snaps.is_complete_snapshot(_payload(ids=(1, 2, 5, 200)))


@pytest.mark.parametrize("hour", [[], [{"netuid": 1}]])
def test_the_hour_horizon_must_cover_the_chain_read(hour):
    # The producer only marks coverage complete when every expected netuid has an hour row
    # (copied from day or scored), so an empty or partial hour panel is never a complete state.
    assert not snaps.is_complete_snapshot(_payload(lambda p: p.update(hour=hour), ids=(1, 2)))


def test_self_declared_expected_lists_must_agree_with_the_chain_read():
    def tamper(p):
        p["coverage"]["day"]["expected"] = [1, 999]
        p["coverage"]["membership"]["expected_netuids"] = [999]

    assert not snaps.is_complete_snapshot(_payload(tamper))
    assert not snaps.is_complete_snapshot(_payload(lambda p: (tamper(p), p.update(day=[{"netuid": 999}]))))


def test_the_chain_read_in_the_receipt_matches_the_helper():
    assert _payload()["coverage"]["membership"]["chain"] == chain_dict([1])


JUNK = [None, 0, -1, True, False, "x", "", [], {}, [1], [None], {"a": 1}, float("inf"), float("nan"), 2**70]


def _paths(node, prefix=()):
    yield prefix
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _paths(value, prefix + (key,))
    elif isinstance(node, list) and node:
        yield from _paths(node[0], prefix + (0,))


def _replace(node, path, value):
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(node, dict):
        return {**node, head: _replace(node[head], rest, value)}
    return [_replace(node[0], rest, value)] + node[1:]


def test_the_predicate_is_total_over_the_real_seed_under_junk_injection():
    with open(SEED, encoding="utf-8") as handle:
        seed = json.load(handle)
    assert snaps.is_complete_snapshot(seed)
    checked = 0
    for path in _paths(seed):
        for junk in JUNK:
            snaps.is_complete_snapshot(_replace(seed, path, junk))
            checked += 1
    assert checked > 500


MALFORMED_DAY_COVERAGE = ["day_expected_junk_strings", "day_expected_not_a_list", "coverage_day_not_a_dict"]


@pytest.mark.parametrize("name", MALFORMED_DAY_COVERAGE)
def test_malformed_day_coverage_is_incomplete_and_reading_it_does_not_raise(name, tmp_path):
    payload = _payload(CHAIN_AND_ROW_SHAPES[name])
    assert snaps.is_complete_snapshot(payload) is False
    volume = tmp_path / "explicit_volume.json"
    volume.write_text(json.dumps(payload), encoding="utf-8")
    served = snaps.read_served_snapshot(str(volume), SEED)
    assert served.state is snaps.ServedState.SEED
