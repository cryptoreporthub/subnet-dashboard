"""Fixture gate (R0.2): oracle pins, no tautologies, imports resolve under python -m pytest."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals/fixtures"
EXAM_PREFIXES = ("hard-", "r1b-")


def exam_fixture_dirs() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.is_dir() and p.name.startswith(EXAM_PREFIXES))


def _oracle_fixture_name(dirname: str) -> str:
    for prefix in EXAM_PREFIXES:
        if dirname.startswith(prefix):
            return dirname.replace(prefix, "", 1)
    return dirname


def test_every_hard_fixture_has_oracle_and_repo() -> None:
    for d in exam_fixture_dirs():
        assert (d / "oracle.json").is_file(), d.name
        assert (d / "repo.json").is_file(), d.name
        assert (d / "gate.json").is_file(), d.name


def test_oracle_json_pins_diff_and_no_timing_leaks() -> None:
    for d in exam_fixture_dirs():
        text = (d / "oracle.json").read_text()
        doc = json.loads(text)
        assert doc.get("fixture") == _oracle_fixture_name(d.name) or doc.get("fixture") == d.name, d.name
        assert "diffSha256" in doc or "pytest" in doc, d.name
        assert not re.search(r'"(?:ms|duration\w*)"\s*:', text), d.name


def test_no_tautological_assert_true_in_pass_fixtures() -> None:
    tautology = re.compile(r"assert\s+True\b")
    for d in exam_fixture_dirs():
        doc = json.loads((d / "oracle.json").read_text())
        expected = (doc.get("behavior") or {}).get("expectedVerdict")
        if expected != "PASS":
            continue
        repo = json.loads((d / "repo.json").read_text())
        for path, content in (repo.get("files") or {}).items():
            if not path.endswith(".py") or "test_" not in path:
                continue
            if tautology.search(content or ""):
                raise AssertionError(f"{d.name}: tautology in {path}")
