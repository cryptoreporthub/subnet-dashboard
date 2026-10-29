"""An explicit relative path= is anchored to the repo root like the default, never to the cwd (#1531 3b)."""

from __future__ import annotations

from internal.council.scorer_identity import current_weights_digest, repo_root
from tests.test_snapshot_membership_provenance import _write_soul_map


def test_explicit_relative_path_is_read_from_the_repo_root_not_the_cwd(tmp_path, monkeypatch):
    decoy = _write_soul_map(tmp_path / "data" / "soul_map.json", quant=1.9)
    monkeypatch.chdir(tmp_path)
    anchored = current_weights_digest(str(repo_root() / "data" / "soul_map.json"))
    assert current_weights_digest("data/soul_map.json") == anchored
    assert current_weights_digest(decoy) != anchored  # the decoy really differs
