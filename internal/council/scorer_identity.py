"""Scoring-semantics identity stamped on every complete snapshot (#1479 PR-B).

Digest covers the four council scoring modules (state_vector, weights,
confidence_calibration, scoring_context). Runtime soul_map JSON is excluded;
a weight-only deploy must change ``weights.py`` (or another listed file) so
``scorer_digest`` mismatches and forces a snapshot rebuild — see
``test_scorer_digest_changes_when_weights_bytes_change``.
"""

from __future__ import annotations

import hashlib
import math
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

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


def _canonical_digest(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def finite_number(value: Any) -> bool:
    """True for an exact int or float that is finite; never raises.

    ``math.isfinite`` converts an int to a float first, so a JSON integer such as ``10**400`` makes it
    raise OverflowError. Such a number is not a usable score or weight: answer False, do not crash.
    """
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def current_weights_digest(path: Optional[str] = None) -> Optional[str]:
    """Digest of the learned council + signal weights in ledger.db, or None when it cannot be read.

    None means "unknown", never "defaults": a corrupt soul_map (at first import) or a corrupt
    ledger.db must not produce a digest, because that digest would equal the one stamped on any
    snapshot built while the store was equally unreadable. A soul_map that was missing or held no
    council weight seeds defaults, and defaults stay "unknown" until a weight is written. Callers treat None as not fresh
    and not publishable.

    ``weights.SOUL_MAP_PATH`` is cwd-relative; anchoring it to the repo root keeps the identity
    the same from any cwd (production cwd /app, volume mounted at /app/data).
    """
    from internal.council import weights

    soul = path or weights.SOUL_MAP_PATH
    if not os.path.isabs(soul):
        soul = str(_REPO_ROOT / soul)
    from internal.store import ledger_db
    from internal.store.ledger_db import LedgerUnreadable

    try:
        if not ledger_db.weights_known(soul):
            return None
        council = weights.load_weights(soul)
        signal = weights.load_signal_weights(soul)
    except LedgerUnreadable:
        return None
    except OverflowError:
        # A weight that is a JSON integer too large for a float (the loaders call float() on it) is
        # corrupt: the weights are unknown, not an error for the caller to handle.
        return None
    return _canonical_digest({"council": council, "signal": signal})


def compute_input_digest(
    membership_generation: str,
    scorer_digest: str,
    rows: Iterable[Dict[str, Any]],
    weights: Dict[str, Any],
) -> str:
    """Value digest of everything a build scored from; no paths, so no cwd dependence."""
    ordered = sorted(rows, key=lambda row: int(row["netuid"]))
    return _canonical_digest(
        {
            "v": 1,
            "generation": membership_generation,
            "scorer_digest": scorer_digest,
            "rows": ordered,
            "weights": weights,
        }
    )


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
