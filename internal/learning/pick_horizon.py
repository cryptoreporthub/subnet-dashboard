"""Council day-pick horizon — canonical 24h (P0.5).

Short-term desks (hour picks, pump_lead) keep their own horizons. Council day
predictions evaluate on a fixed 24h window. The Acc-2 env rollback knobs
``ACC2_DAY_HORIZON_HOURS`` / ``DAY_PICK_HORIZON_HOURS`` are no longer honored
so a 4h desk horizon cannot silently reattach to Council.
"""

from __future__ import annotations

# Canonical Council day evaluation horizon (hours).
COUNCIL_DAY_HORIZON_HOURS = 24


def day_horizon_hours() -> int:
    """Horizon for council day picks and ledger rows — locked to 24h (P0.5)."""
    return int(COUNCIL_DAY_HORIZON_HOURS)
