"""Fly web vs worker process mode (Phase B load separation)."""

from __future__ import annotations

import os


def get_run_mode() -> str:
    return os.environ.get("RUN_MODE", "web").strip().lower()


def is_worker_mode() -> bool:
    return get_run_mode() == "worker"


def background_on_web() -> bool:
    """True when this process should start resolver/feed/sync (legacy combined mode)."""
    if is_worker_mode():
        return False
    return os.environ.get("BACKGROUND_ON_WEB", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def worker_mode_label() -> str:
    """web | worker | combined — for /api/ops/readiness."""
    if is_worker_mode():
        return "worker"
    if background_on_web():
        return "combined"
    return "web"
