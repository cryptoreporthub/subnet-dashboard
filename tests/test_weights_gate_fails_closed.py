"""A missing or corrupt soul_map must not look like "default weights" to the producer gate (#1484, review item 4)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from internal.council import weights
from internal.council.scorer_identity import current_weights_digest
from tests.score_snapshot_testutil import complete_snapshot_payload
from tests.test_snapshot_membership_provenance import _producer_env, _universe

REPO = Path(__file__).resolve().parents[1]


def _soul(tmp_path, text=None, name="soul_map.json"):
    path = tmp_path / name
    if text is not None:
        path.write_text(text)
    return str(path)


# A valid soul_map that has no learned weights yet: the digest is the default weights' digest.
_VALID_NO_LEARNED_WEIGHTS = json.dumps({"last_updated": "2026-10-28T00:00:00Z"})
_UNUSABLE = {
    "missing": None,
    "corrupt": "{not json",
    "truncated": '{"adversarial_state": {"council_weights": {"quant": 1.',
    "empty_file": "",
    "empty_object": "{}",
    "not_an_object": "[1, 2, 3]",
}


@pytest.mark.parametrize("kind", sorted(_UNUSABLE))
def test_digest_is_none_when_the_soul_map_is_unusable(tmp_path, kind):
    assert current_weights_digest(_soul(tmp_path, _UNUSABLE[kind])) is None


def test_digest_is_a_string_when_the_soul_map_is_usable(tmp_path):
    digest = current_weights_digest(_soul(tmp_path, _VALID_NO_LEARNED_WEIGHTS))
    assert isinstance(digest, str) and len(digest) == 64


def _volume_with_default_weights_stamp(tmp_path, monkeypatch, soul_path):
    """A volume snapshot stamped with the default-weights digest, and the gate pointed at ``soul_path``."""
    default_digest = current_weights_digest(_soul(tmp_path, _VALID_NO_LEARNED_WEIGHTS, "defaults.json"))
    snap = copy.deepcopy(complete_snapshot_payload())
    snap["provenance"]["weights_digest"] = default_digest
    volume = tmp_path / "score_snapshots.json"
    volume.write_text(json.dumps(snap))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    return volume


def test_gate_is_true_when_the_soul_map_is_usable_and_the_digest_matches(tmp_path, monkeypatch):
    soul = _soul(tmp_path, _VALID_NO_LEARNED_WEIGHTS, "live.json")
    volume = _volume_with_default_weights_stamp(tmp_path, monkeypatch, soul)
    assert snaps.is_complete_snapshot(json.loads(volume.read_text())) is True
    assert snaps.volume_has_fresh_complete_snapshot(str(volume), max_age_seconds=0) is True


@pytest.mark.parametrize("kind", ["missing", "corrupt", "truncated", "empty_object"])
def test_gate_is_false_when_the_soul_map_is_unusable_even_if_stamped_with_default_weights(tmp_path, monkeypatch, kind):
    soul = _soul(tmp_path, _UNUSABLE[kind], "live.json")
    volume = _volume_with_default_weights_stamp(tmp_path, monkeypatch, soul)
    assert snaps.volume_has_fresh_complete_snapshot(str(volume), max_age_seconds=0) is False


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_producer_refuses_to_publish_without_usable_weights_and_keeps_last_good(tmp_path, monkeypatch, kind):
    volume, soul, _ = _producer_env(tmp_path, monkeypatch, _universe([1, 2, 3]))
    good = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 5.0, "name": "A"}])
    assert snaps.publish_complete_snapshot(good, str(volume))["published"]
    before = volume.read_bytes()
    if kind == "missing":
        Path(soul).unlink()
    else:
        Path(soul).write_text("{not json")
    from internal.store import soul_map_io

    soul_map_io._cache.clear()

    out = snaps.write_full_universe_snapshot()

    assert out["published"] is False
    assert out["coverage"]["capture_reason"] == "weights_unavailable"
    assert volume.read_bytes() == before


def test_first_boot_without_a_soul_map_still_serves_the_committed_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", _soul(tmp_path))  # nothing written: first boot
    served = snaps.read_served_snapshot(
        path=str(tmp_path / "no_volume.json"),
    )
    assert served.servable is True
    assert served.origin == "seed"


def _count_hydrates(monkeypatch):
    calls = []
    original = __import__("server")._get_subnets_hydrate

    def counting():
        calls.append(1)
        return original()

    monkeypatch.setattr("server._get_subnets_hydrate", counting)
    return calls


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_an_unusable_soul_map_skips_the_build_before_any_loading_or_scoring(tmp_path, monkeypatch, kind):
    volume, soul, scored = _producer_env(tmp_path, monkeypatch, _universe([1, 2, 3]))
    hydrates = _count_hydrates(monkeypatch)
    monkeypatch.setattr(snaps, "_weights_available", None, raising=False)
    _break_soul_map(soul, kind)

    out = snaps.write_full_universe_snapshot()

    assert out["published"] is False
    assert out["skipped"] == "weights_unavailable"
    assert out["coverage"]["capture_reason"] == "weights_unavailable"
    assert scored == []  # nothing was scored
    assert hydrates == []  # not even the subnet feed was loaded
    assert not volume.exists()
    cycle = json.loads((tmp_path / "cycle.json").read_text())
    assert cycle["capture_reason"] == "weights_unavailable"


def _break_soul_map(soul, kind):
    from internal.store import soul_map_io

    if kind == "missing":
        Path(soul).unlink()
    else:
        Path(soul).write_text("{not json")
    soul_map_io._cache.clear()


def _weights_records(caplog):
    return [r for r in caplog.records if "weights_unavailable" in r.getMessage() or "weights available again" in r.getMessage()]


def test_the_skip_logs_once_per_state_change_and_recovers_when_the_soul_map_returns(tmp_path, monkeypatch, caplog):
    import logging

    volume, soul, scored = _producer_env(tmp_path, monkeypatch, _universe([1, 2, 3]))
    monkeypatch.setattr(snaps, "_weights_available", None, raising=False)
    good_blob = Path(soul).read_text()
    _break_soul_map(soul, "missing")

    with caplog.at_level(logging.INFO, logger=snaps.logger.name):
        for _ in range(3):
            assert snaps.write_full_universe_snapshot()["skipped"] == "weights_unavailable"
        down = _weights_records(caplog)
        assert [r.levelno for r in down] == [logging.WARNING]  # one line for three skipped cycles

        # The soul_map comes back: the next cycle builds and publishes, and says so once.
        Path(soul).write_text(good_blob)
        from internal.store import soul_map_io

        soul_map_io._cache.clear()
        out = snaps.write_full_universe_snapshot()
        assert out["published"] is True
        assert scored  # it really scored
        assert snaps.write_full_universe_snapshot()["published"] is True
        up = _weights_records(caplog)
        assert [r.levelno for r in up] == [logging.WARNING, logging.INFO]

        # Lost again: a new state change logs again, once.
        _break_soul_map(soul, "corrupt")
        for _ in range(2):
            assert snaps.write_full_universe_snapshot()["skipped"] == "weights_unavailable"
        again = _weights_records(caplog)
        assert [r.levelno for r in again] == [logging.WARNING, logging.INFO, logging.WARNING]


def test_the_scheduler_tick_itself_creates_a_usable_soul_map(tmp_path, monkeypatch):
    """Why first boot is cheap in production: a tick records its summary in the soul_map before building."""
    from internal.store import soul_map_io

    soul = tmp_path / "fresh" / "soul_map.json"
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(soul))
    soul_map_io._cache.clear()
    assert current_weights_digest() is None

    snaps.ScoreSnapshotScheduler()._persist_cycle_summary({"run_at": "2026-10-28T00:00:00Z", "ok": False})

    assert soul.exists()
    assert isinstance(current_weights_digest(), str)
