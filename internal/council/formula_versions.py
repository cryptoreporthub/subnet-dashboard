"""Formula version tracking — bump on calibration fire with holdout beat record."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.dark_horse_crash import FORMULA_VERSION as DARK_HORSE_FORMULA_VERSION
from internal.council.human_narrative import calibration_version_story
from internal.council.weights import _load_raw, _save_raw

_DEFAULT_COUNCIL_VERSION = "1.0"
# ponytail: max ~1 minor bump / 7d + 1pp holdout gain — avoids v12 in two weeks of daily retrains
_MIN_DAYS_BETWEEN_BUMPS = 7
_MIN_HOLDOUT_IMPROVEMENT = 0.01


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_version(version: str) -> tuple:
    parts = str(version or _DEFAULT_COUNCIL_VERSION).strip().lstrip("v").split(".")
    nums = [int(p) for p in parts if p.isdigit()]
    while len(nums) < 2:
        nums.append(0)
    return tuple(nums[:3])


def _bump_minor(version: str) -> str:
    major, minor, *_rest = _parse_version(version)
    return f"{major}.{minor + 1}"


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(ts: str) -> Optional[float]:
    then = _parse_iso(ts)
    if then is None:
        return None
    return (datetime.now(timezone.utc) - then.astimezone(timezone.utc)).total_seconds() / 86400.0


def _holdout_improvement(cert: Dict[str, Any]) -> Optional[float]:
    proposed = cert.get("proposed_accuracy")
    current = cert.get("current_accuracy")
    if proposed is None or current is None:
        return None
    try:
        return float(proposed) - float(current)
    except (TypeError, ValueError):
        return None


def _should_bump_minor(
    council: Dict[str, Any],
    *,
    cert: Dict[str, Any],
    forced: bool,
    beat_previous: Optional[bool],
) -> bool:
    if forced or not cert.get("passed") or beat_previous is False:
        return False
    improvement = _holdout_improvement(cert)
    if improvement is not None and improvement < _MIN_HOLDOUT_IMPROVEMENT:
        return False
    for entry in reversed(council.get("history") or []):
        if not entry.get("version_bumped"):
            continue
        last_at = entry.get("fired_at")
        days = _days_since(last_at) if last_at else None
        if days is not None and days < _MIN_DAYS_BETWEEN_BUMPS:
            return False
        break
    return True


def load_formula_versions(path: str = "data/soul_map.json") -> Dict[str, Any]:
    data = _load_raw(path)
    adv = data.get("adversarial_state") if isinstance(data.get("adversarial_state"), dict) else {}
    versions = adv.get("formula_versions")
    if not isinstance(versions, dict):
        versions = {}
    versions.setdefault(
        "council_weights",
        {"current": _DEFAULT_COUNCIL_VERSION, "history": []},
    )
    versions.setdefault(
        "dark_horse_scoring",
        {
            "current": DARK_HORSE_FORMULA_VERSION,
            "history": [],
            "note": "Code-level scoring version (crash-tail blend).",
        },
    )
    return versions


def record_calibration_version(
    *,
    cert: Dict[str, Any],
    weights_before: Dict[str, float],
    weights_after: Dict[str, float],
    soul_map_path: str = "data/soul_map.json",
    forced: bool = False,
) -> Dict[str, Any]:
    """Bump council weights version when calibration fires; record holdout beat."""
    data = _load_raw(soul_map_path)
    adv = data.setdefault("adversarial_state", {})
    if not isinstance(adv, dict):
        adv = {}
        data["adversarial_state"] = adv

    versions = load_formula_versions(soul_map_path)
    council = versions.setdefault("council_weights", {"current": _DEFAULT_COUNCIL_VERSION, "history": []})
    prev_version = str(council.get("current") or _DEFAULT_COUNCIL_VERSION)
    proposed_acc = cert.get("proposed_accuracy")
    current_acc = cert.get("current_accuracy")
    beat_previous: Optional[bool] = None
    if proposed_acc is not None and current_acc is not None:
        beat_previous = float(proposed_acc) >= float(current_acc)

    version_bumped = _should_bump_minor(
        council, cert=cert, forced=forced, beat_previous=beat_previous
    )
    next_version = _bump_minor(prev_version) if version_bumped else prev_version

    entry = {
        "version": next_version,
        "previous_version": prev_version,
        "version_bumped": version_bumped,
        "fired_at": _utcnow_z(),
        "holdout_proposed_accuracy": proposed_acc,
        "holdout_previous_accuracy": current_acc,
        "holdout_improvement_pp": (
            round(_holdout_improvement(cert) * 100, 2)
            if _holdout_improvement(cert) is not None
            else None
        ),
        "beat_previous": beat_previous,
        "forced": forced,
        "cert_passed": bool(cert.get("passed")),
        "weights_before": {k: round(float(v), 4) for k, v in weights_before.items()},
        "weights_after": {k: round(float(v), 4) for k, v in weights_after.items()},
        "story": calibration_version_story(
            prev_version,
            next_version,
            proposed_acc,
            current_acc,
            beat_previous,
            forced,
            version_bumped=version_bumped,
        ),
    }
    history: List[Dict[str, Any]] = list(council.get("history") or [])
    history.append(entry)
    if version_bumped:
        council["current"] = next_version
    council["history"] = history[-20:]
    versions["council_weights"] = council
    adv["formula_versions"] = versions
    _save_raw(data, soul_map_path)
    return entry
