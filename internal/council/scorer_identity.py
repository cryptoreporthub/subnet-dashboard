"""Scoring-semantics identity stamped on every complete snapshot (#1479 PR-B)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict

SCORER_REVISION = 1

_SCORER_SOURCE_FILES = (
    "internal/council/state_vector.py",
    "internal/council/weights.py",
    "internal/council/confidence_calibration.py",
)


def current_scorer_digest() -> str:
    """Stable hash of scoring code paths (not runtime soul_map weights)."""
    digest = hashlib.sha256()
    for rel in _SCORER_SOURCE_FILES:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            with open(rel, "rb") as handle:
                digest.update(handle.read())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()[:16]


def stamp_scorer_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["scorer_revision"] = SCORER_REVISION
    out["scorer_digest"] = current_scorer_digest()
    return out


def scorer_fields_match(snap: Dict[str, Any]) -> bool:
    try:
        revision = int(snap.get("scorer_revision"))
    except (TypeError, ValueError):
        return False
    if revision != SCORER_REVISION:
        return False
    return str(snap.get("scorer_digest") or "") == current_scorer_digest()
