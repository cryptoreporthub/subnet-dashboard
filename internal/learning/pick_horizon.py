"""Day-pick horizon config (Acc-2 knob A — align ledger with 24h council lens)."""

from __future__ import annotations

import os

_DEFAULT_DAY_HOURS = 24


def day_horizon_hours() -> int:
    """Horizon for council day picks and ledger rows (rollback: ACC2_DAY_HORIZON_HOURS=4)."""
    raw = os.environ.get(
        "ACC2_DAY_HORIZON_HOURS",
        os.environ.get("DAY_PICK_HORIZON_HOURS", str(_DEFAULT_DAY_HOURS)),
    ).strip()
    try:
        hours = int(raw)
    except ValueError:
        hours = _DEFAULT_DAY_HOURS
    return max(1, min(48, hours))
