"""Plain-language Dev Signals summary for mindmap panels (Phase C)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.dev_radar.github_sync import load_dev_radar_cache


def _sentences(parts: List[str]) -> Dict[str, Any]:
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return {"text": text, "sentences": [p.strip() for p in parts if p and p.strip()]}


def summarize_dev_signals() -> Dict[str, Any]:
    """Summarize dev_radar_cache.json — display-only, no prediction loop."""
    cache = load_dev_radar_cache()
    subnets = cache.get("subnets") if isinstance(cache.get("subnets"), dict) else {}
    parts: List[str] = []

    if not subnets:
        parts.append(
            "Dev Signals cache is empty — GitHub velocity sync runs on the worker when "
            "DEV_RADAR_GITHUB_SYNC is enabled; until then only registry repo flags are shown."
        )
        return _sentences(parts)

    synced = sum(1 for row in subnets.values() if isinstance(row, dict) and row.get("velocity_score") is not None)
    gap_rows = [
        row
        for row in subnets.values()
        if isinstance(row, dict) and row.get("gap_signal") == "dev_ahead_of_price"
    ]
    parts.append(
        f"Dev Pulse tracks GitHub velocity for {synced} subnet repos "
        f"(cache updated {cache.get('updated_at') or 'unknown'})."
    )
    if gap_rows:
        top = sorted(gap_rows, key=lambda r: float(r.get("gap_score") or 0), reverse=True)[0]
        parts.append(
            f"{len(gap_rows)} subnet(s) show dev activity ahead of price — strongest gap "
            f"score {float(top.get('gap_score') or 0):.0f} (commits_7d={top.get('commits_7d')})."
        )
    else:
        parts.append(
            "No dev-ahead-of-price gap signals in the latest cache window — "
            "velocity and price moves are roughly aligned."
        )
    parts.append("Display-only feed: dev spikes do not auto-score picks or nudge expert weights.")
    return _sentences(parts[:4])
