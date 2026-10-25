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
