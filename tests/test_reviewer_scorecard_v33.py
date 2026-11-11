"""Known-answer fixture and Wilson checks for reviewer scorecard v3.3 phase 1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.reviewer_scorecard.blind import compute_blind
from tools.reviewer_scorecard.generator import generate_from_directory, generate_scorecard
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
        if os.environ.get("SCORECARD_REGENERATE_GOLDEN", "").strip().lower() in {"1", "true", "yes"}:
            GOLDEN_DET.write_bytes(generated.deterministic_bytes)
        else:
            pytest.fail(
                f"missing golden fixture {GOLDEN_DET}; set SCORECARD_REGENERATE_GOLDEN=1 to create it"
            )
    golden = GOLDEN_DET.read_bytes()
    assert generated.deterministic_bytes == golden


def test_false_pass_only_when_at_risk_not_caught_on_head() -> None:
    tables = ScorecardTables(
        bugs=[
            {
                "bug_id": "s1_one",
                "status": "real",
                "severity": "S1 Critical",
            }
        ],
        presence=[
            {"bug_id": "s1_one", "head_sha": "head_a", "state": "present", "scope": "diff"},
        ],
        reviews=[
            {
                "reviewer_id": "sharp",
                "pr": "42",
                "head_sha": "head_a",
                "stage": "code",
                "claimed_verdict": "pass",
                "coverage_class": "clean",
                "counting": "yes",
                "requested_at": "2026-01-01T10:00:00Z",
                "verdict_at": "2026-01-01T11:00:00Z",
                "caught_bug_ids": "s1_one",
            },
            {
                "reviewer_id": "miss",
                "pr": "43",
                "head_sha": "head_b",
                "stage": "code",
                "claimed_verdict": "pass",
                "coverage_class": "clean",
                "counting": "yes",
                "requested_at": "2026-01-02T10:00:00Z",
                "verdict_at": "2026-01-02T11:00:00Z",
                "caught_bug_ids": "-",
            },
        ],
        registry=[{"reviewer_id": "sharp"}, {"reviewer_id": "miss"}],
        confirms=[],
        root=Path("."),
    )
    tables.presence.append({"bug_id": "s1_one", "head_sha": "head_b", "state": "present", "scope": "diff"})
    sharp = compute_reviewer_metrics(tables, "sharp")
    miss = compute_reviewer_metrics(tables, "miss")
    assert sharp.headlines.false_passes == 0
    assert sharp.correct_clean_passes == 1
    assert miss.headlines.false_passes == 1
    assert miss.correct_clean_passes == 0


def test_serious_caught_only_at_risk_and_counting_blind() -> None:
    tables = ScorecardTables(
        bugs=[
            {"bug_id": "s1_real", "status": "real", "severity": "S1 Critical"},
            {"bug_id": "s4_noise", "status": "real", "severity": "S4 Low"},
        ],
        presence=[
            {"bug_id": "s1_real", "head_sha": "head_c", "state": "present", "scope": "diff"},
        ],
        reviews=[
            {
                "reviewer_id": "mix",
                "pr": "50",
                "head_sha": "head_c",
                "stage": "code",
                "claimed_verdict": "modify",
                "coverage_class": "non_counting",
                "counting": "no",
                "requested_at": "2026-01-03T08:00:00Z",
                "verdict_at": "2026-01-03T09:00:00Z",
                "caught_bug_ids": "s1_real;s4_noise;ghost_bug",
            }
        ],
        registry=[{"reviewer_id": "mix"}],
        confirms=[],
        root=Path("."),
    )
    m = compute_reviewer_metrics(tables, "mix")
    assert m.headlines.serious_caught == 1
    assert m.headlines.serious_caught_blind == 0


def test_comment_keys_unique_per_reviewer_and_full_head() -> None:
    tables = ScorecardTables(
        bugs=[],
        reviews=[
            {
                "reviewer_id": "r1",
                "pr": "1",
                "head_sha": "abcdef0",
                "stage": "code",
                "claimed_verdict": "pass",
                "coverage_class": "clean",
                "counting": "yes",
                "requested_at": "",
                "verdict_at": "",
            },
            {
                "reviewer_id": "r1",
                "pr": "1",
                "head_sha": "abcdef1",
                "stage": "code",
                "claimed_verdict": "pass",
                "coverage_class": "clean",
                "counting": "yes",
                "requested_at": "",
                "verdict_at": "",
            },
        ],
        presence=[],
        registry=[{"reviewer_id": "r1", "display_name": "R1"}],
        confirms=[],
        root=TABLE_DIR,
    )
    out = generate_scorecard(tables)
    assert "r1_abcdef0" in out.reviewer_comments
    assert "r1_abcdef1" in out.reviewer_comments
    assert len(out.reviewer_comments) == 2


def test_deterministic_bytes_use_structural_clock_strip(tables: ScorecardTables) -> None:
    generated = generate_from_directory(TABLE_DIR)
    payload = json.loads(generated.deterministic_bytes.decode("utf-8"))
    assert payload["json"]["generated_at"] is None
    assert "<clock-stripped>" in next(iter(payload["peer_comments"].values()))
    assert "<verdict_at> UTC" in next(iter(payload["reviewer_comments"].values()))
    assert "2026-01-" not in generated.deterministic_bytes.decode("utf-8")


def test_tsv_zero_byte_error_and_header_only_ok(tmp_path: Path) -> None:
    root = tmp_path / "tables"
    root.mkdir()
    for name in (
        "bugs.tsv",
        "reviews.tsv",
        "bug_head_presence.tsv",
        "reviewers.registry.tsv",
        "confirms.tsv",
    ):
        src = TABLE_DIR / name
        (root / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    empty = root / "confirms.tsv"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="zero-byte"):
        ScorecardTables.load(root)

    empty.write_text("bug_id\tconfirmed_by\tevidence_kind\tevidence_link\tconfirmed_at\n", encoding="utf-8")
    loaded = ScorecardTables.load(root)
    assert loaded.confirms == []


def test_blind_same_head_peer_citation_is_informed() -> None:
    rows = [
        {
            "reviewer_id": "peer",
            "head_sha": "h1",
            "verdict_at": "2026-01-01T09:00:00Z",
        },
        {
            "reviewer_id": "late",
            "head_sha": "h1",
            "verdict_at": "2026-01-01T11:00:00Z",
        },
    ]
    blind = compute_blind(
        "late",
        "h1",
        "2026-01-01T08:00:00Z",
        rows,
        same_head_peer_citation="yes",
    )
    assert blind == "no"


def test_blind_uses_stored_when_requested_at_missing() -> None:
    assert compute_blind("r", "h", "", [], stored_blind="yes") == "yes"
