"""Gate must reject known-bad fixture revisions from git history (R0.2 acceptance)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gate_core import historical_rejection, load_repo_json_at

REPO = Path(__file__).resolve().parents[3]

# (git sha, repo.json path, human label)
KNOWN_BAD: list[tuple[str, str, str]] = [
    ("9fa53fd9", "exam-artifacts/r25/fixtures/r25-p7-v2/repo.json", "r27/r25 p7-v2 wrong 729 vs 629"),
    ("5310cbc6", "exam-artifacts/r27/fixtures/r27-p5-v2/repo.json", "r27 p5-v2 bare pytest"),
    ("8ac92798", "review-gate-bot/evals/fixtures/hard-r24-consolidation-drops-coverage/repo.json", "r24 consolidation-v1 assert True"),
    ("8ac92798", "review-gate-bot/evals/fixtures/hard-r24-removal-guarded-b/repo.json", "r24 removal-guarded-b assert True"),
    ("57da9995", "exam-artifacts/r25/fixtures/r25-p6/repo.json", "r25 p6 behavior change"),
]

# Parent of r27-P4-FAIL fix: shard 1 collects nothing
_p4_parent = subprocess.run(
    ["git", "-C", str(REPO), "rev-parse", "50f1edda^"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
KNOWN_BAD.append((_p4_parent, "exam-artifacts/r27/fixtures/r27-p4/repo.json", "r27 p4 first version shard-1 empty"))


@pytest.mark.parametrize("rev,path,label", KNOWN_BAD)
def test_known_bad_fixture_is_rejected(rev: str, path: str, label: str) -> None:
    doc = load_repo_json_at(REPO, rev, path)
    assert doc is not None, f"missing {rev}:{path}"
    py = str(REPO / ".venv/bin/python") if (REPO / ".venv/bin/python").is_file() else None
    errors = historical_rejection(REPO, rev, path, label, doc, python=py)
    assert errors, f"expected gate to reject {label} @ {rev} but got no errors"
