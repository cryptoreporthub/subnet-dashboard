"""Known-answer fixture and Wilson checks for reviewer scorecard v3.3 phase 1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.reviewer_scorecard.blind import compute_blind
from tools.reviewer_scorecard.generator import generate_from_directory
from tools.reviewer_scorecard.metrics import compute_reviewer_metrics
from tools.reviewer_scorecard.tables import ScorecardTables
from tools.reviewer_scorecard.wilson import wilson_lower_bound

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tools/reviewer_scorecard/fixtures/known_answer"
TABLE_DIR = FIXTURE_ROOT / "tables"
EXPECTED_PATH = FIXTURE_ROOT / "expected_metrics.json"
GOLDEN_DET = FIXTURE_ROOT / "golden_scorecard.det.json"


@pytest.fixture(scope="module")
def tables() -> ScorecardTables:
    return ScorecardTables.load(TABLE_DIR)


@pytest.fixture(scope="module")
def expected() -> dict:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def test_wilson_matches_design_table(expected: dict) -> None:
    for row in expected["design_wilson_table"]:
        got = wilson_lower_bound(row["successes"], row["n"])
        assert got is not None
        assert got == pytest.approx(row["lb"], rel=0, abs=1e-5)


def test_fixture_rubber_metrics(tables: ScorecardTables, expected: dict) -> None:
    m = compute_reviewer_metrics(tables, "rubber")
    exp = expected["reviewers"]["rubber"]
    assert m.headlines.heads_reviewed == exp["heads_reviewed"]
    assert m.clean_pass_n == exp["clean_pass_n"]
    assert m.correct_clean_passes == exp["correct_clean_passes"]
    assert m.pass_precision_lb == pytest.approx(exp["pass_precision_lb"], abs=1e-6)
    assert m.headlines.false_passes == exp["false_passes"]
    assert m.headlines.false_pass_denominator == exp["false_pass_denominator"]
    assert m.at_risk_bugs_reviewed == exp["at_risk_bugs_reviewed"]
    assert m.repo_at_risk_bugs == exp["repo_at_risk_bugs"]


def test_fixture_catcher_once_per_bug(tables: ScorecardTables, expected: dict) -> None:
    m = compute_reviewer_metrics(tables, "catcher")
    exp = expected["reviewers"]["catcher"]
    assert m.headlines.serious_caught == exp["serious_caught"]
    assert m.clean_pass_n == exp["clean_pass_n"]
    assert m.headlines.false_passes == exp["false_passes"]
    assert m.pass_precision_lb == pytest.approx(exp["pass_precision_lb"], abs=1e-6)
    assert m.at_risk_bugs_reviewed == exp["at_risk_bugs_reviewed"]


def test_unknown_and_degraded_and_dead(tables: ScorecardTables, expected: dict) -> None:
    unknown = compute_reviewer_metrics(tables, "unknown_cov")
    assert unknown.clean_pass_n == 0
    assert unknown.headlines.non_counting_share == pytest.approx(1.0)
    degraded = compute_reviewer_metrics(tables, "degraded_r")
    assert degraded.headlines.degraded_pass_count == expected["reviewers"]["degraded_r"]["degraded_pass_count"]
    assert degraded.clean_pass_n == 0
    dead = compute_reviewer_metrics(tables, "dead_r")
    assert dead.per_review[0]["coverage_class"] == "incomplete"
    assert dead.per_review[0]["counting"] is False


def test_blind_computation(tables: ScorecardTables, expected: dict) -> None:
    rows = [r for r in tables.reviews if r["head_sha"] == "syn_h0006"]
    by_id = {r["reviewer_id"]: r for r in rows}
    blind_a = compute_blind("blind_a", "syn_h0006", by_id["blind_a"]["requested_at"], rows)
    blind_b = compute_blind("blind_b", "syn_h0006", by_id["blind_b"]["requested_at"], rows)
    assert blind_a == expected["reviewers"]["blind_a"]["per_head_blind"]["syn_h0006"]
    assert blind_b == expected["reviewers"]["blind_b"]["per_head_blind"]["syn_h0006"]


def test_generator_deterministic_bytes_stable(tables: ScorecardTables, tmp_path: Path) -> None:
    first = generate_from_directory(TABLE_DIR, tmp_path / "a")
    second = generate_from_directory(TABLE_DIR, tmp_path / "b")
    assert first.deterministic_bytes == second.deterministic_bytes
    assert first.scorecard_json["schema_version"] == "scorecard.json/3.3.0"
    assert first.scorecard_json["inputs_hash"] == tables.inputs_hash()
    assert any(k.startswith("rubber_") for k in first.reviewer_comments)
    assert any(k.startswith("catcher_") for k in first.peer_comments)


def test_golden_deterministic_payload(tables: ScorecardTables) -> None:
    generated = generate_from_directory(TABLE_DIR)
    if not GOLDEN_DET.exists():
        GOLDEN_DET.write_bytes(generated.deterministic_bytes)
    golden = GOLDEN_DET.read_bytes()
    assert generated.deterministic_bytes == golden
