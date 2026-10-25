"""Scoring-semantics identity stamped on every complete snapshot (#1479 PR-B).

Digest covers the four council scoring modules (state_vector, weights,
confidence_calibration, scoring_context). Runtime soul_map JSON is excluded;
a weight-only deploy must change ``weights.py`` (or another listed file) so
``scorer_digest`` mismatches and forces a snapshot rebuild — see
``test_scorer_digest_changes_when_weights_bytes_change``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Tuple

SCORER_REVISION = 1

# ponytail: runtime soul_map weights are intentionally excluded — digest tracks code
# that defines how scores are computed. Amendment 6333635162: scoring_context carries
# market/pump inputs into score_subnet_for_* ; the four council experts live in
# state_vector + weights + confidence_calibration.
_SCORER_SOURCE_FILES: Tuple[str, ...] = (
    "internal/council/state_vector.py",
    "internal/council/weights.py",
    "internal/council/confidence_calibration.py",
    "internal/council/scoring_context.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return _REPO_ROOT


def scorer_source_paths() -> Tuple[Path, ...]:
    return tuple(_REPO_ROOT / rel for rel in _SCORER_SOURCE_FILES)


def current_scorer_digest() -> str:
    """Stable hash of scoring code paths (cwd-independent)."""
    digest = hashlib.sha256()
    for path in scorer_source_paths():
        digest.update(str(path.relative_to(_REPO_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()[:16]


def stamp_scorer_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["scorer_revision"] = SCORER_REVISION
    out["scorer_digest"] = current_scorer_digest()
    return out


def scorer_fields_match(snap: Dict[str, Any]) -> bool:
    revision = snap.get("scorer_revision")
    if type(revision) is not int or revision != SCORER_REVISION:
        return False
    return snap.get("scorer_digest") == current_scorer_digest()


def scorer_identity_file_list() -> Tuple[str, ...]:
    """Documented scoring-identity surface (tests + PR body)."""
    return _SCORER_SOURCE_FILES
