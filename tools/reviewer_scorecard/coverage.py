"""Coverage class and counting rules (design §3)."""

from __future__ import annotations

from typing import Literal

CoverageClass = Literal["clean", "degraded", "incomplete", "non_counting"]


def parse_files_count(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw or raw.lower() in {"not_adjudicated", "unknown", "na"}:
        return -1
    if raw.isdigit():
        return int(raw)
    # path-list: count semicolon-separated paths
    return len([p for p in raw.split(";") if p.strip()])


def derive_counting(coverage_class: str, stage: str, counting_column: str) -> bool:
    if counting_column.strip().lower() in {"no", "false", "0"}:
        return False
    if counting_column.strip().lower() in {"yes", "true", "1"}:
        return True
    if stage.strip().lower() == "plan":
        return False
    if coverage_class in {"non_counting", "incomplete"}:
        return False
    return True


def is_clean_pass(claimed_verdict: str, coverage_class: str) -> bool:
    return claimed_verdict.strip().lower() == "pass" and coverage_class == "clean"
