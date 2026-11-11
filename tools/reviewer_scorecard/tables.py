"""Load TSV source tables for the reviewer scorecard."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TABLE_NAMES = (
    "bugs.tsv",
    "reviews.tsv",
    "bug_head_presence.tsv",
    "reviewers.registry.tsv",
    "confirms.tsv",
)

REQUIRED_BUG_FIELDS = (
    "bug_id",
    "pr",
    "first_head_sha",
    "fixed_head_sha",
    "status",
    "confirmed_by",
    "severity",
    "stage",
)
REQUIRED_PRESENCE_FIELDS = ("bug_id", "head_sha", "state", "scope")
REQUIRED_REVIEW_FIELDS = (
    "reviewer_id",
    "pr",
    "head_sha",
    "stage",
    "claimed_verdict",
    "coverage_class",
    "counting",
    "files_reviewed",
    "files_changed",
    "requested_at",
    "verdict_at",
    "blind",
)
REQUIRED_REGISTRY_FIELDS = ("reviewer_id", "display_name", "system", "model_version")
REQUIRED_CONFIRM_FIELDS = ("bug_id", "confirmed_by", "evidence_kind", "evidence_link", "confirmed_at")


def _read_tsv(path: Path) -> list[dict[str, str]]:
    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{path.name}: zero-byte TSV")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"{path.name}: not a valid TSV")
        rows = [dict(row) for row in reader]
    return rows


def _require_fields(rows: list[dict[str, str]], fields: tuple[str, ...], label: str) -> None:
    if not rows:
        return
    missing = [f for f in fields if f not in rows[0]]
    if missing:
        raise ValueError(f"{label}: missing columns {missing}")


@dataclass(frozen=True)
class ScorecardTables:
    bugs: list[dict[str, str]]
    reviews: list[dict[str, str]]
    presence: list[dict[str, str]]
    registry: list[dict[str, str]]
    confirms: list[dict[str, str]]
    root: Path

    @classmethod
    def load(cls, root: Path) -> ScorecardTables:
        bugs = _read_tsv(root / "bugs.tsv")
        reviews = _read_tsv(root / "reviews.tsv")
        presence = _read_tsv(root / "bug_head_presence.tsv")
        registry = _read_tsv(root / "reviewers.registry.tsv")
        confirms = _read_tsv(root / "confirms.tsv")
        _require_fields(bugs, REQUIRED_BUG_FIELDS, "bugs.tsv")
        _require_fields(presence, REQUIRED_PRESENCE_FIELDS, "bug_head_presence.tsv")
        _require_fields(reviews, REQUIRED_REVIEW_FIELDS, "reviews.tsv")
        _require_fields(registry, REQUIRED_REGISTRY_FIELDS, "reviewers.registry.tsv")
        _require_fields(confirms, REQUIRED_CONFIRM_FIELDS, "confirms.tsv")
        return cls(bugs, reviews, presence, registry, confirms, root)

    def inputs_hash(self) -> str:
        parts: list[bytes] = []
        for name in TABLE_NAMES:
            parts.append((self.root / name).read_bytes())
        digest = hashlib.sha256(b"".join(parts)).hexdigest()
        return digest[:16]
