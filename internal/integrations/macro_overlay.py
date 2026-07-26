"""Subnet macro signal overlay for council scoring (Synth / Numinous / DeSearch / ReadyAI)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

_CACHE: Dict[str, Any] = {"at": 0.0, "overlay": {}}
_CACHE_TTL = 300


def _overlay_alpha() -> float:
    raw = os.environ.get("MACRO_OVERLAY_ALPHA", "0.08").strip()
    try:
        alpha = float(raw)
    except (TypeError, ValueError):
        alpha = 0.08
    return max(0.0, min(0.20, alpha))


def _tailwind_from_signals(payload: Dict[str, Any]) -> Tuple[str, float, list]:
    """Map integration signals → mood label + ±score tailwind (0–100 scale)."""
    mood = str(payload.get("mood") or "neutral")
    sources: list = []
    tailwind = 0.0
    for sig in payload.get("signals") or []:
        slug = sig.get("slug")
        if slug:
            sources.append(slug)
        if slug == "synth":
            data = sig.get("data") if isinstance(sig.get("data"), dict) else {}
            # ponytail: coarse parse; upgrade when Synth schema is pinned in contract tests
            text = str(data).lower()
            if "bull" in text or "above" in text:
                tailwind += 2.0
                mood = "bullish_tailwind"
            elif "bear" in text or "below" in text:
                tailwind -= 2.0
                mood = "bearish_headwind"
            else:
                tailwind += 1.0
        elif slug == "numinous":
            tailwind += 0.5
        elif slug == "desearch":
            tailwind += 0.75
        elif slug == "readyai":
            tailwind += 0.25
    tailwind = max(-4.0, min(4.0, tailwind))
    return mood, tailwind, sources


def build_macro_overlay(*, force: bool = False) -> Dict[str, Any]:
    """Cached macro overlay for market_context (5 min TTL)."""
    now = time.time()
    if not force and _CACHE["overlay"] and now - _CACHE["at"] < _CACHE_TTL:
        return dict(_CACHE["overlay"])
    try:
        from internal.integrations.signals import build_macro_signals

        payload = build_macro_signals()
    except Exception:
        payload = {"mood": "unavailable", "signals": [], "signal_count": 0}
    mood, tailwind, sources = _tailwind_from_signals(payload)
    overlay = {
        "mood": mood,
        "tailwind": tailwind,
        "sources": sources,
        "signal_count": payload.get("signal_count", 0),
        "alpha": _overlay_alpha(),
    }
    _CACHE["at"] = now
    _CACHE["overlay"] = overlay
    return dict(overlay)


def apply_macro_score_overlay(
    total_score: float,
    market_context: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Apply global macro tailwind to council total (0–100)."""
    overlay = (market_context or {}).get("macro_overlay")
    if not overlay:
        return total_score, None
    alpha = float(overlay.get("alpha") or 0)
    if alpha <= 0:
        return total_score, None
    tailwind = float(overlay.get("tailwind") or 0)
    if tailwind == 0:
        return total_score, None
    adjusted = round(float(total_score) + tailwind * alpha * 10, 2)
    adjusted = min(100.0, max(0.0, adjusted))
    return adjusted, {
        "tailwind": tailwind,
        "alpha": alpha,
        "mood": overlay.get("mood"),
        "sources": overlay.get("sources") or [],
    }
