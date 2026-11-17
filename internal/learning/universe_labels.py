"""Universe-wide forward labels: one realised move per scoring-universe netuid.

A label is the move from the last close at or before ``t0`` to the last close
at or before ``t0 + horizon``. It reads only price candles, never scores, so a
name is labelled whether or not the council picked it. The exit candle must be
no older than ``max_stale`` before the horizon, so a stalled feed reads as
``no_exit`` instead of a stale move.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATUS_OK = "ok"
STATUS_NO_ENTRY = "no_entry"
STATUS_NO_EXIT = "no_exit"


@dataclass(frozen=True)
class ForwardLabel:
    netuid: int
    t0: datetime
    horizon: timedelta
    status: str
    entry_close: Optional[float] = None
    exit_close: Optional[float] = None

    @property
    def forward_return(self) -> Optional[float]:
        if self.status != STATUS_OK or not self.entry_close:
            return None
        return self.exit_close / self.entry_close - 1.0


def parse_ts(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def closes_from_candles(candles: Iterable[Dict[str, Any]]) -> List[Tuple[datetime, float]]:
    """Sorted ``(timestamp, close)`` pairs, dropping rows without a usable close."""
    out: List[Tuple[datetime, float]] = []
    for row in candles or []:
        try:
            close = float(row["close"])
            ts = parse_ts(str(row["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
        if close > 0:
            out.append((ts, close))
    out.sort(key=lambda pair: pair[0])
    return out


def _last_at_or_before(closes: List[Tuple[datetime, float]], at: datetime) -> Optional[Tuple[datetime, float]]:
    found = None
    for ts, close in closes:
        if ts > at:
            break
        found = (ts, close)
    return found


def forward_label(
    netuid: int,
    closes: List[Tuple[datetime, float]],
    t0: datetime,
    horizon: timedelta,
    *,
    max_stale: timedelta = timedelta(hours=2),
) -> ForwardLabel:
    entry = _last_at_or_before(closes, t0)
    if entry is None or t0 - entry[0] > max_stale:
        return ForwardLabel(netuid, t0, horizon, STATUS_NO_ENTRY)
    end = t0 + horizon
    exit_ = _last_at_or_before(closes, end)
    if exit_ is None or exit_[0] <= entry[0] or end - exit_[0] > max_stale:
        return ForwardLabel(netuid, t0, horizon, STATUS_NO_EXIT, entry_close=entry[1])
    return ForwardLabel(netuid, t0, horizon, STATUS_OK, entry_close=entry[1], exit_close=exit_[1])


def universe_labels(
    price_cache: Dict[str, Any],
    netuids: Iterable[int],
    t0: datetime,
    horizon: timedelta,
    *,
    max_stale: timedelta = timedelta(hours=2),
) -> List[ForwardLabel]:
    """One label per netuid. Cache keys are ``"N"`` for candle history (``"N.alpha"`` holds a spot price only)."""
    labels: List[ForwardLabel] = []
    for netuid in netuids:
        entry = price_cache.get(str(netuid))
        candles = entry.get("candles") if isinstance(entry, dict) else None
        closes = closes_from_candles(candles or [])
        labels.append(forward_label(netuid, closes, t0, horizon, max_stale=max_stale))
    return labels
