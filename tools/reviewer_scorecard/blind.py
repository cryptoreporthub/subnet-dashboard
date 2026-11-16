"""Compute blind flag from requested_at vs peer verdict_at (design §1)."""

from __future__ import annotations

from datetime import datetime, timezone


def _parse_ts(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_blind(
    reviewer_id: str,
    head_sha: str,
    requested_at: str,
    reviews_at_head: list[dict[str, str]],
    stored_blind: str | None = None,
    same_head_peer_citation: str | None = None,
) -> str:
    """Return blind ('yes') or informed ('no') from timing; design §1 overrides."""
    if (same_head_peer_citation or "").strip().lower() in {"yes", "true", "1"}:
        return "no"

    req = _parse_ts(requested_at)
    if req is None:
        stored = (stored_blind or "no").strip().lower()
        return stored if stored in {"yes", "no"} else "no"

    peer_times: list[datetime] = []
    for row in reviews_at_head:
        if row["reviewer_id"] == reviewer_id:
            continue
        vt = _parse_ts(row.get("verdict_at", ""))
        if vt is not None:
            peer_times.append(vt)

    if not peer_times:
        return "no"
    earliest_peer = min(peer_times)
    if req < earliest_peer:
        return "yes"
    return "no"
