"""Membership provenance on score snapshots (#1479 PR-B, act-on 1).

Real SnapshotBuilder / _read_chain / ChainReader code; only the RPC transport and the
TMC fetch are injected, replaying a recorded chain read.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload

from internal.chain_price import config as chain_cfg
from internal.chain_read import ChainRead
from internal import subnet_universe as su
from internal.council import snapshot_coverage as cov

FIXTURE = Path(__file__).parent / "fixtures" / "chain" / "bm_9280796.json"
RECORDED_HEAD = "0x72a82add74d481216a2f4b8f77e7729f88b2abf0654a9c6be89a3cf10f7cedd0"


class _ReplayClient:
    """Answers from the recorded block-9280796 read; counts calls."""

    def __init__(self, recorded):
        self._recorded = recorded
        self.calls = 0

    def _call_typed(self, method, params=None):
        self.calls += 1
        if method == "chain_getFinalizedHead":
            return RECORDED_HEAD
        return self._recorded[f"{method}|{json.dumps(params or [])}"]

    def query_storage_at(self, keys, at_hash):
        return self._call_typed("state_queryStorageAt", [keys, at_hash])


class _DeadClient:
    def _call_typed(self, method, params=None):
        raise RuntimeError("provider down")


@pytest.fixture
def recorded_providers(monkeypatch):
    recorded = json.loads(FIXTURE.read_text())
    providers = [("finney", _DeadClient()), ("blockmachine", _ReplayClient(recorded))]
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: providers)
    return providers


def test_membership_block_and_rpc_survive_builder_and_persist(recorded_providers):
    chain = su._read_chain()
    assert chain is not None
    assert chain.block_hash == RECORDED_HEAD
    assert chain.rpc == "blockmachine"  # finney failed; the provider that answered is the label

    def tmc():
        members = set(chain.netuids)
        return members, {n: {"netuid": n, "name": f"N{n}"} for n in members}, True

    built = su.SnapshotBuilder(tmc_fetch=tmc).build(None).snapshot
    assert built.chain is not None
    assert (built.chain.block_hash, built.chain.rpc) == (RECORDED_HEAD, "blockmachine")

    reloaded = su.UniverseSnapshot.from_dict(json.loads(json.dumps(built.to_dict())))
    assert (reloaded.chain.block_hash, reloaded.chain.rpc) == (RECORDED_HEAD, "blockmachine")


def test_rpc_is_a_provider_label_never_a_url():
    raw = {"block_hash": RECORDED_HEAD, "netuids": [1, 2]}
    assert ChainRead.parse({**raw, "rpc": "finney"}).rpc == "finney"
    assert ChainRead.parse(raw).rpc is None  # a universe file written before rpc existed still loads
    leaked = ChainRead.parse({**raw, "rpc": "https://rpc.example/?key=secret"})
    assert leaked is not None and leaked.rpc is None
    assert "secret" not in json.dumps(leaked.to_dict())


def _universe(chain_netuids, *, universe_netuids=None, block="ab", rpc="finney"):
    """A fresh, ok universe. ``universe_netuids`` may keep a grace row the chain no longer lists."""
    ids = tuple(universe_netuids if universe_netuids is not None else chain_netuids)
    return su.UniverseSnapshot(
        netuids=ids,
        rows=tuple({"netuid": n, "name": f"N{n}"} for n in ids),
        resolved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status="ok",
        degraded=False,
        chain=ChainRead("0x" + block * 32, tuple(sorted(chain_netuids)), rpc),
    )


def _receipt_for(monkeypatch, universe):
    monkeypatch.setattr(su, "get_snapshot", lambda: universe)
    return cov.load_membership_receipt()


def test_generation_is_the_hash_of_the_sorted_positive_expected_set():
    # Expected value computed outside this code base: sha256 of
    # {"expected_netuids":[1..128],"v":1} (sorted keys, compact separators), first 16 hex.
    assert cov.membership_generation(range(1, 129)) == "mg1:2324225a288eb818"
    assert cov.membership_generation([3, 1, 2]) == cov.membership_generation([1, 2, 3])
    assert cov.membership_generation([0, 1, 2, 3]) == cov.membership_generation([1, 2, 3])
    assert cov.membership_generation([1, 2]) != cov.membership_generation([1, 2, 3])


def test_receipt_carries_generation_block_hash_and_rpc_of_the_chain_read(monkeypatch):
    receipt = _receipt_for(monkeypatch, _universe([1, 2, 3], block="cd", rpc="blockmachine"))
    assert receipt["generation"] == cov.membership_generation([1, 2, 3])
    assert receipt["block_hash"] == "0x" + "cd" * 32
    assert receipt["rpc"] == "blockmachine"


def test_generation_moves_at_dereg_not_block_or_grace_expiry(monkeypatch):
    base = _receipt_for(monkeypatch, _universe([1, 2, 77, 78]))["generation"]

    new_block = _receipt_for(monkeypatch, _universe([1, 2, 77, 78], block="ef", rpc="blockmachine"))
    assert new_block["generation"] == base

    # 77 deregisters on chain; its universe row stays for the 48h grace.
    dereg = _receipt_for(monkeypatch, _universe([1, 2, 78], universe_netuids=[1, 2, 77, 78]))
    assert dereg["generation"] != base
    assert 77 not in dereg["expected_netuids"]

    # Grace expires: the row leaves the universe, the chain set is unchanged.
    expired = _receipt_for(monkeypatch, _universe([1, 2, 78]))
    assert expired["generation"] == dereg["generation"]


_PROVENANCE_GAPS = {
    "no_rpc": lambda u: _with_chain(u, ChainRead("0x" + "ab" * 32, (1, 2, 3), None)),
    "no_chain_read": lambda u: _with_chain(u, None),
}


def _with_chain(universe, chain):
    return su.UniverseSnapshot(
        netuids=universe.netuids,
        rows=universe.rows,
        resolved_at=universe.resolved_at,
        status=universe.status,
        degraded=False,
        chain=chain,
    )


@pytest.mark.parametrize("gap", sorted(_PROVENANCE_GAPS))
def test_admission_is_blocked_without_chain_provenance(monkeypatch, gap):
    universe = _PROVENANCE_GAPS[gap](_universe([1, 2, 3]))
    receipt = _receipt_for(monkeypatch, universe)
    assert cov.membership_allows_admission(receipt) is False
    assert cov.membership_admission_block_reason(receipt) == "membership_without_chain_provenance"
    assert cov.membership_allows_admission(_receipt_for(monkeypatch, _universe([1, 2, 3]))) is True


def _producer_env(tmp_path, monkeypatch, universe, *, scorer=None):
    """Real write_full_universe_snapshot over a fixed universe; scoring itself is stubbed."""
    from internal.council import weights

    soul = _write_soul_map(tmp_path / "soul" / "soul_map.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul)
    volume = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(volume))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(su, "get_snapshot", lambda: universe)
    hydrate = [{"netuid": n, "name": f"N{n}", "price": 1.0, "volume": 10.0} for n in universe.netuids]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
    scored = []

    def _score(sn, ctx):
        scored.append((dict(sn), ctx))
        if scorer:
            scorer()
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _score)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    return volume, soul, scored


def test_unprovenanced_membership_gates_the_producer_and_keeps_last_good(tmp_path, monkeypatch):
    pre_1483 = _with_chain(_universe([1, 2]), None)  # universe file written before the chain fields
    volume, _, _ = _producer_env(tmp_path, monkeypatch, pre_1483)
    good = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 5.0, "name": "A"}])
    assert snaps.publish_complete_snapshot(good, str(volume))["published"]
    before = volume.read_bytes()

    out = snaps.write_full_universe_snapshot()

    assert out["published"] is False
    cycle = json.loads((tmp_path / "cycle.json").read_text())
    assert cycle["membership_admission_gate_reason"] == "membership_without_chain_provenance"
    assert volume.read_bytes() == before
    served = snaps.read_served_snapshot()
    assert served.servable and served.state.value in ("fresh", "aged")


def test_complete_build_carries_exactly_the_six_provenance_fields(tmp_path, monkeypatch):
    from internal.council.scorer_identity import compute_input_digest, current_scorer_digest, current_weights_digest

    universe = _universe([1, 2, 3], block="cd", rpc="blockmachine")
    volume, soul, scored = _producer_env(tmp_path, monkeypatch, universe)

    assert snaps.write_full_universe_snapshot()["published"] is True

    prov = json.loads(volume.read_text())["provenance"]
    generation = cov.membership_generation([1, 2, 3])
    assert set(prov) == {
        "membership_generation",
        "membership_block_hash",
        "membership_rpc",
        "membership_resolved_at",
        "weights_digest",
        "input_digest",
    }
    assert prov["membership_generation"] == generation
    assert prov["membership_block_hash"] == "0x" + "cd" * 32
    assert prov["membership_rpc"] == "blockmachine"
    assert prov["membership_resolved_at"] == universe.resolved_at
    assert prov["weights_digest"] == current_weights_digest(soul)
    # The digest covers what the scorer was actually handed: its rows and its ctx weights.
    rows = [row for row, _ in scored]
    assert sorted(r["netuid"] for r in rows) == [1, 2, 3]
    assert prov["input_digest"] == compute_input_digest(
        generation, current_scorer_digest(), rows, scored[0][1]["weights"]
    )


def test_weights_digest_is_the_one_taken_at_build_start(tmp_path, monkeypatch):
    from internal.council.scorer_identity import current_weights_digest
    from internal.store.soul_map_io import write_soul_map

    universe = _universe([1, 2])
    soul_holder = {}

    def _edit_weights_mid_build():
        blob = {"adversarial_state": {"council_weights": {"quant": 1.9, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}}
        write_soul_map(lambda b: (b.clear(), b.update(blob)), soul_holder["path"])

    volume, soul, _ = _producer_env(tmp_path, monkeypatch, universe, scorer=_edit_weights_mid_build)
    soul_holder["path"] = soul
    at_start = current_weights_digest(soul)

    assert snaps.write_full_universe_snapshot()["published"] is True

    assert json.loads(volume.read_text())["provenance"]["weights_digest"] == at_start
    assert current_weights_digest(soul) != at_start  # the edit really happened


REPO = Path(__file__).resolve().parents[1]
ROWS = [
    {"netuid": 2, "name": "B", "price": 2.0, "volume": 20.0},
    {"netuid": 1, "name": "A", "price": 1.0, "volume": 10.0},
]


def _write_soul_map(path, *, quant=1.0, signal_tweak=None):
    blob = {"adversarial_state": {"council_weights": {"quant": quant, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}}
    if signal_tweak is not None:
        blob["adversarial_state"]["signal_weights"] = {"day": signal_tweak}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob))
    return str(path)


_DIGEST_PROBE = """
import json
from internal.council.scorer_identity import compute_input_digest, current_scorer_digest, current_weights_digest
rows = %r
print(json.dumps([current_weights_digest(), compute_input_digest("mg1:x", current_scorer_digest(), rows, {"quant": 1.0})]))
"""


def _digests_from(cwd):
    out = subprocess.run(
        [sys.executable, "-c", _DIGEST_PROBE % (ROWS,)],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO), "DISABLE_BACKGROUND_SCANS": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def test_digests_are_cwd_independent(tmp_path):
    # A decoy soul_map in the other cwd: a cwd-relative read would pick it up.
    elsewhere = tmp_path / "elsewhere"
    _write_soul_map(elsewhere / "data" / "soul_map.json", quant=1.7)
    assert _digests_from(REPO) == _digests_from(elsewhere)


def test_weights_digest_follows_council_and_signal_weights(tmp_path):
    from internal.council.scorer_identity import current_weights_digest

    base = current_weights_digest(_write_soul_map(tmp_path / "a.json"))
    assert current_weights_digest(_write_soul_map(tmp_path / "a2.json")) == base
    council = current_weights_digest(_write_soul_map(tmp_path / "b.json", quant=1.5))
    signal = current_weights_digest(_write_soul_map(tmp_path / "c.json", signal_tweak={"rsi_crossover": 1.9}))
    assert len({base, council, signal}) == 3


def test_input_digest_covers_rows_and_weights():
    from internal.council.scorer_identity import compute_input_digest

    def digest(rows=ROWS, weights=None, generation="mg1:a", scorer="s1"):
        return compute_input_digest(generation, scorer, rows, weights or {"quant": 1.0})

    base = digest()
    assert digest(rows=list(reversed(ROWS))) == base  # row order is not an input
    assert digest(rows=[{**ROWS[0], "price": 9.0}, ROWS[1]]) != base
    assert digest(weights={"quant": 1.1}) != base
    assert digest(generation="mg1:b") != base
    assert digest(scorer="s2") != base


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serve_fresh_volume(tmp_path, monkeypatch, netuids):
    """A fresh complete snapshot on the volume for ``netuids``."""
    volume = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(volume))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    payload = complete_snapshot_payload(
        day_rows=[{"netuid": n, "total_score": float(n), "name": f"N{n}"} for n in netuids],
        written_at=_now_iso(),
    )
    assert snaps.publish_complete_snapshot(payload, str(volume))["published"]
    return volume


def test_reader_keeps_serving_and_labels_membership_moved(tmp_path, monkeypatch):
    _serve_fresh_volume(tmp_path, monkeypatch, [1, 2, 3])

    monkeypatch.setattr(su, "get_snapshot", lambda: _universe([1, 2, 3]))
    same = snaps.build_top_picks_from_snapshot(None)["meta"]
    assert same["membership_current"] is True
    assert same["stale_alert"] is False

    monkeypatch.setattr(su, "get_snapshot", lambda: _universe([1, 2]))  # netuid 3 deregistered
    served = snaps.read_served_snapshot()
    assert served.servable and served.state.value == "fresh"
    picks = snaps.build_top_picks_from_snapshot(None)
    assert picks["day_picks"]
    assert picks["meta"]["membership_current"] is False
    assert picks["meta"]["stale_alert"] is True


def test_membership_current_is_null_when_membership_is_not_admissible(tmp_path, monkeypatch):
    _serve_fresh_volume(tmp_path, monkeypatch, [1, 2, 3])
    degraded = dataclasses.replace(_universe([1, 2]), status="degraded", degraded=True)
    monkeypatch.setattr(su, "get_snapshot", lambda: degraded)

    meta = snaps.build_top_picks_from_snapshot(None)["meta"]

    assert meta["membership_current"] is None
    assert meta["stale_alert"] is False  # nothing is known to have moved


def test_producer_gate_not_current_after_membership_or_weights_change(tmp_path, monkeypatch):
    from internal.store.soul_map_io import write_soul_map

    universe = _universe([1, 2, 3])
    volume, soul, _ = _producer_env(tmp_path, monkeypatch, universe)
    assert snaps.write_full_universe_snapshot()["published"] is True
    assert snaps.volume_has_fresh_complete_snapshot() is True

    # Weights move: the reader still serves, the producer gate says "build again".
    blob = {"adversarial_state": {"council_weights": {"quant": 1.8, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}}
    write_soul_map(lambda b: (b.clear(), b.update(blob)), soul)
    assert snaps.volume_has_fresh_complete_snapshot() is False
    assert snaps.read_served_snapshot().state.value == "fresh"

    # Weights restored, membership moves.
    write_soul_map(lambda b: (b.clear(), b.update({"adversarial_state": {"council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}})), soul)
    assert snaps.volume_has_fresh_complete_snapshot() is True
    monkeypatch.setattr(su, "get_snapshot", lambda: _universe([1, 2]))
    assert snaps.volume_has_fresh_complete_snapshot() is False
    assert snaps.read_served_snapshot().servable


def _tmc_for(netuids, extra=()):
    ids = set(netuids) | set(extra)

    def tmc():
        rows = {n: {"netuid": n, "name": f"Net {n}", "price": 1.0 + n / 100, "volume": 1000.0 + n} for n in ids}
        return ids, rows, True

    return tmc


@pytest.fixture
def real_membership(recorded_providers):
    """The universe that SnapshotBuilder resolves from the recorded chain read (a real refresh)."""
    chain = su._read_chain()
    built = su.SnapshotBuilder(tmc_fetch=_tmc_for(chain.netuids, extra=[9999])).build(None).snapshot
    return built


def _seed(tmp_path, membership):
    from internal.council import build_seed_snapshot as seed_build

    out = seed_build.build_image_seed_snapshot(
        membership=membership, volume_path=str(tmp_path / "seed.json"), cycle_path=str(tmp_path / "cycle.json")
    )
    return out, tmp_path / "seed.json"


def test_seed_scores_exactly_the_membership_result(tmp_path, monkeypatch, real_membership):
    _write_soul_map(tmp_path / "soul" / "soul_map.json")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(tmp_path / "soul" / "soul_map.json"))
    chain = real_membership.chain
    dereg = chain.netuids[5]
    # The chain no longer lists `dereg`; its universe row survives the 48h grace.
    moved = dataclasses.replace(
        real_membership,
        chain=ChainRead(chain.block_hash, tuple(n for n in chain.netuids if n != dereg), chain.rpc),
    )
    assert dereg in {r["netuid"] for r in moved.rows}

    out, path = _seed(tmp_path, moved)

    assert out["published"] is True
    snap = json.loads(path.read_text())
    expected = [n for n in chain.netuids if n != dereg]
    assert sorted(r["netuid"] for r in snap["day"]) == expected
    assert 9999 not in {r["netuid"] for r in snap["day"]}
    assert snap["provenance"]["membership_generation"] == cov.membership_generation(expected)
    assert snap["provenance"]["membership_block_hash"] == chain.block_hash
    assert snap["provenance"]["membership_rpc"] == chain.rpc


_REFUSALS = {
    "no_block": (lambda m: dataclasses.replace(m, chain=None), "membership_without_chain_provenance"),
    "no_rpc": (
        lambda m: dataclasses.replace(m, chain=ChainRead(m.chain.block_hash, m.chain.netuids, None)),
        "membership_without_chain_provenance",
    ),
    "degraded": (lambda m: dataclasses.replace(m, status="degraded", degraded=True), "degraded"),
    "emergency": (lambda m: dataclasses.replace(m, status="emergency_registry", degraded=True), "emergency_registry"),
}


@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_seed_refuses_unprovenanced_or_inadmissible_membership(tmp_path, real_membership, case):
    mutate, reason = _REFUSALS[case]

    out, path = _seed(tmp_path, mutate(real_membership))

    assert out["published"] is False
    assert out["refused"] == reason
    assert not path.exists()


def _load_refresh_script():
    spec = importlib.util.spec_from_file_location("refresh_score_snapshot_seed", REPO / "scripts" / "refresh_score_snapshot_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_script_builds_the_seed_from_the_chain_receipt_path(tmp_path, monkeypatch, recorded_providers):
    _write_soul_map(tmp_path / "soul" / "soul_map.json")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(tmp_path / "soul" / "soul_map.json"))
    chain = su._read_chain()
    monkeypatch.setattr(su, "_default_tmc_fetch", _tmc_for(chain.netuids))
    dest = tmp_path / "seed.json"

    rc = _load_refresh_script().main(["--build-from-chain", "--dest", str(dest)])

    assert rc == 0
    seed = json.loads(dest.read_text())
    assert [r["netuid"] for r in seed["day"]] and sorted(r["netuid"] for r in seed["day"]) == list(chain.netuids)
    assert seed["provenance"]["membership_block_hash"] == RECORDED_HEAD
    assert seed["provenance"]["membership_rpc"] == "blockmachine"
    assert seed["provenance"]["membership_generation"] == "mg1:2324225a288eb818"


def test_refresh_script_with_the_rpcs_down_exits_nonzero_and_leaves_the_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: [("finney", _DeadClient()), ("blockmachine", _DeadClient())])
    monkeypatch.setattr(su, "_default_tmc_fetch", _tmc_for(range(1, 20)))
    dest = tmp_path / "seed.json"
    dest.write_text('{"keep": "me"}')
    before = hashlib.sha256(dest.read_bytes()).hexdigest()

    rc = _load_refresh_script().main(["--build-from-chain", "--dest", str(dest)])

    assert rc != 0
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == before


def _edit(path, value):
    """Return a mutator that sets the dotted ``path`` (``None`` value deletes the key)."""

    def apply(snap):
        node = snap
        *parents, leaf = path.split(".")
        for key in parents:
            node = node[key]
        if value is None:
            node.pop(leaf)
        else:
            node[leaf] = value

    return apply


def _add_day_row(snap):
    snap["day"].append({"netuid": 99, "total_score": 1.0, "name": "X"})
    snap["hour"].append({"netuid": 99, "total_score": 1.0, "name": "X"})


_INCONSISTENT = {
    "missing_provenance": _edit("provenance", None),
    "generation_mismatch": _edit("provenance.membership_generation", "mg1:0000000000000000"),
    "receipt_generation_mismatch": _edit("coverage.membership.generation", "mg1:0000000000000000"),
    "edited_expected_list": _edit("coverage.membership.expected_netuids", [1, 2, 3]),
    "bad_block": _edit("provenance.membership_block_hash", "0x1234"),
    "block_differs_from_chain": _edit("provenance.membership_block_hash", "0x" + "11" * 32),
    "rpc_is_a_url": _edit("provenance.membership_rpc", "https://rpc.example/?key=k"),
    "no_input_digest": _edit("provenance.input_digest", None),
    "no_weights_digest": _edit("provenance.weights_digest", None),
    "row_outside_membership": _add_day_row,
    "no_expected_netuids_key": _edit("coverage.membership.expected_netuids", None),
    "no_fresh_key": _edit("coverage.membership.fresh", None),
    "provenance_is_a_string": lambda snap: snap.__setitem__("provenance", "x"),
    "provenance_is_a_list": lambda snap: snap.__setitem__("provenance", [1]),
    "no_receipt_generation": _edit("coverage.membership.generation", None),
    "rpc_label_differs_from_chain": _edit("provenance.membership_rpc", "blockmachine"),
    "empty_weights_digest": _edit("provenance.weights_digest", ""),
    "non_string_input_digest": _edit("provenance.input_digest", 7),
    "fresh_is_truthy_but_not_true": _edit("coverage.membership.fresh", "yes"),
    "declared_day_expected_differs_from_chain": _edit("coverage.day.expected", [1, 2, 3]),
}


def test_complete_snapshot_with_consistent_provenance_is_complete():
    assert snaps.is_complete_snapshot(complete_snapshot_payload()) is True


@pytest.mark.parametrize("case", sorted(_INCONSISTENT))
def test_complete_requires_consistent_provenance(case):
    snap = complete_snapshot_payload()
    _INCONSISTENT[case](snap)
    assert snaps.is_complete_snapshot(snap) is False
