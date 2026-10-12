"""Deadline-aware Pipe framing for live_subnets parent/child IPC."""

from __future__ import annotations

import time
from typing import Any, Optional


def recv_message(conn, deadline: float) -> Optional[Any]:
    """Receive one pickled object before ``deadline`` (monotonic clock).

    Uses poll slices so a false-positive ``poll()`` cannot wedge on blocking
    ``recv()`` past the budget.
    """
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        wait = min(remaining, 0.25)
        if not conn.poll(wait):
            if time.monotonic() >= deadline:
                return None
            continue
        try:
            return conn.recv()
        except (EOFError, OSError, BrokenPipeError):
            return None


def send_message(conn, payload: Any) -> bool:
    try:
        conn.send(payload)
        return True
    except (EOFError, OSError, BrokenPipeError):
        return False
