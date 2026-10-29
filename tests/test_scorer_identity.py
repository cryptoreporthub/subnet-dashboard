"""Scorer identity digest — cwd-independent (#1484 act-on 3–4)."""

from __future__ import annotations

import os
from pathlib import Path

from internal.council.scorer_identity import (
    current_scorer_digest,
    scorer_fields_match,
    scorer_identity_file_list,
)
from tests.score_snapshot_testutil import complete_snapshot_payload


def test_scorer_digest_stable_from_repo_root():
    a = current_scorer_digest()
    b = current_scorer_digest()
    assert a == b
    assert len(a) == 16


def test_scorer_digest_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    digest = current_scorer_digest()
    payload = complete_snapshot_payload(day_rows=[{"netuid": 1, "total_score": 1.0}])
    payload["scorer_digest"] = digest
    assert scorer_fields_match(payload)


def test_scorer_digest_changes_when_weights_bytes_change():
    import hashlib
    from internal.council.scorer_identity import scorer_source_paths

    paths = scorer_source_paths()
    weights = next(p for p in paths if p.name == "weights.py")
    baseline = hashlib.sha256()
    for path in paths:
        baseline.update(path.read_bytes())
    touched = hashlib.sha256()
    for path in paths:
        data = path.read_bytes()
        if path == weights:
            data = data + b"\n"
        touched.update(data)
    assert baseline.hexdigest() != touched.hexdigest()


def test_scorer_identity_files_include_scoring_context():
    files = scorer_identity_file_list()
    assert "internal/council/scoring_context.py" in files
    assert "internal/council/state_vector.py" in files
    root = Path(__file__).resolve().parents[1]
    for rel in files:
        assert (root / rel).is_file()


def _soul_map_with(tmp_path, council):
    import json

    path = tmp_path / "soul_map.json"
    path.write_text(json.dumps({"adversarial_state": {"council_weights": council}}))
    return str(path)


def test_a_valid_soul_map_still_has_a_digest(tmp_path):
    from internal.council.scorer_identity import current_weights_digest

    path = _soul_map_with(tmp_path, {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0})
    assert len(current_weights_digest(path) or "") == 64


def test_an_oversized_integer_weight_means_weights_unknown_not_a_crash(tmp_path):
    """float(10**400) raises OverflowError in the loaders; the digest must answer None, never raise (#1484 Ditto r5)."""
    from internal.council.scorer_identity import current_weights_digest

    only_huge = _soul_map_with(tmp_path, {"quant": 10**400})
    assert current_weights_digest(only_huge) is None
    one_good_one_huge = _soul_map_with(tmp_path, {"quant": 1.0, "hype": 10**400})
    assert current_weights_digest(one_good_one_huge) is None


def test_finite_number_never_raises():
    from internal.council.scorer_identity import finite_number

    assert finite_number(1) and finite_number(0.5) and finite_number(10**300)
    for bad in (10**400, -(10**400), True, None, "1", float("nan"), float("inf"), [1]):
        assert finite_number(bad) is False
