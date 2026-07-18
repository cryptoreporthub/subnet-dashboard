"""Plain-English stories for formula lineage, evolution, and calibration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pct(rate: Optional[float]) -> str:
    if rate is None:
        return "n/a"
    try:
        return f"{float(rate) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def calibration_version_story(
    prev_version: str,
    next_version: str,
    proposed_acc: Optional[float],
    current_acc: Optional[float],
    beat_previous: Optional[bool],
    forced: bool = False,
    version_bumped: bool = True,
) -> str:
    """One-liner when council weights version bumps on calibration fire."""
    if forced:
        return (
            f"Admin override — weights updated, still on council v{prev_version}. "
            f"Holdout check was skipped."
        )
    if not version_bumped and beat_previous is True and proposed_acc is not None:
        return (
            f"Still on v{prev_version}. Holdout looks good ({_pct(proposed_acc)}), "
            f"but we only tick the version when the gain is meaningful and at least "
            f"a week has passed since the last bump."
        )
    if version_bumped and beat_previous is True and proposed_acc is not None and current_acc is not None:
        return (
            f"v{next_version} beat v{prev_version} on holdout "
            f"({_pct(proposed_acc)} vs {_pct(current_acc)}). New weights are live."
        )
    if beat_previous is False and proposed_acc is not None and current_acc is not None:
        return (
            f"v{prev_version} held — holdout did not improve "
            f"({_pct(proposed_acc)} vs {_pct(current_acc)})."
        )
    return f"Council weights refreshed on v{prev_version} after calibration."


def lineage_catalog_summary() -> str:
    return (
        "Every voice on the council has a paper trail — where the idea came from, "
        "what we changed for subnets, and how live picks tune the dial over time."
    )


def lineage_loop_note() -> str:
    return (
        "The research papers stay frozen in time. What moves is us: each graded pick "
        "nudges weights, and when calibration fires a new version has to beat the last "
        "one on holdout — or the swap does not ship."
    )


def dark_horse_formula_summary() -> str:
    return (
        "Hunts hidden value after stress — blends crash-tail price signals with "
        "on-chain conviction (pool depth, supply squeeze, cheap vs emissions)."
    )


def origin_story(label: str, inspiration_citation: str, formula_expression: str, weight: float) -> str:
    cite = inspiration_citation.split(".")[0] if inspiration_citation else "published research"
    return (
        f"{label} started from {cite}. "
        f"We kept the spirit, rewrote the math for subnet data. "
        f"Starting council weight: {weight:.2f}."
    )


def subnet_window_story(
    label: str,
    day: str,
    acc: Optional[float],
    acc_delta: Optional[float],
    triggers: List[Dict[str, Any]],
    n_picks: int,
) -> str:
    names = ", ".join(t["name"] for t in triggers[:3] if t.get("name"))
    acc_txt = _pct(acc)
    if acc_delta is not None and abs(acc_delta) >= 0.12:
        if acc_delta < 0:
            mood = "took a hit"
        else:
            mood = "heated up"
        swing = f"hit-rate {mood} by {abs(acc_delta) * 100:.0f} points"
    else:
        swing = f"graded {n_picks} picks"
    subnet_bit = f" Standouts: {names}." if names else ""
    return f"On {day}, {label} {swing} ({acc_txt} in that window).{subnet_bit}"


def weight_nudge_story(
    label: str,
    day: Optional[str],
    before: float,
    after: float,
    reason: Optional[str],
    subnet: Optional[str],
) -> str:
    direction = "louder" if after > before else "quieter"
    when = f"After {day}, " if day else ""
    sub = f" following {subnet}" if subnet else ""
    why = f" — {reason}" if reason else ""
    return (
        f"{when}{label} got {direction} in the room "
        f"({before:.3f} → {after:.3f}){sub}{why}."
    )


def calibration_episode_story(
    label: str,
    status: Optional[str],
    proposed_w: Optional[float],
    version: Optional[str] = None,
    beat_story: Optional[str] = None,
) -> str:
    if beat_story:
        return beat_story
    if version and status == "fired":
        return f"Calibration shipped council v{version}; {label} weight landed at {proposed_w}."
    if status == "cert_failed":
        return f"Calibration ran but did not pass the safety check — {label} weight stayed put."
    return f"Calibration proposed {label} at {proposed_w} ({status or 'review'})."


def current_state_story(
    label: str,
    current_w: float,
    graded_n: int,
    accuracy: Optional[float],
    formula_version: Optional[str] = None,
) -> str:
    acc_txt = _pct(accuracy) if accuracy is not None else "building sample"
    ver = f" (scoring v{formula_version})" if formula_version else ""
    return (
        f"Right now {label} speaks at weight {current_w:.3f}{ver} — "
        f"{graded_n} graded calls, {acc_txt} lane accuracy."
    )


def evolution_trail_summary(episode_count: int, label: str) -> str:
    return (
        f"{episode_count} chapters for {label}: where it came from, "
        f"when reality disagreed, and how the dial moved."
    )


def episode_kind_label(kind: str) -> str:
    return {
        "origin": "Starting point",
        "subnet_divergence": "Reality check",
        "weight_nudge": "Dial adjustment",
        "calibration": "Calibration",
        "version_upgrade": "Version upgrade",
        "current": "Today",
    }.get(kind, kind.replace("_", " ").title())
