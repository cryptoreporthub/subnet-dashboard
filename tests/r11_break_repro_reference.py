"""MC r11-break-repro reference (logic lives in ``test_stall_guard_run_id_r12.py``).

Hung write-phase token with ``run_id`` and ``progress`` both JSON null / probe-unknown every N checks.
R10: exit ~11 guard ticks @ 240s (~2400s). R11 unconditional ``return False``: no exit in 120 ticks.
"""

from __future__ import annotations

OUTAGE_EVERY_OPTIONS = (2, 3, 4, 5)
R10_WORST_KILL_SECONDS = 2400
