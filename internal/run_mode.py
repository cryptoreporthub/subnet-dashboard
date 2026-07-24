"""Fly web vs worker process mode (Phase B load separation)."""

from __future__ import annotations

import os


def get_run_mode() -> str:
    return os.environ.get("RUN_MODE", "web").strip().lower()


def is_worker_mode() -> bool:
    return get_run_mode() == "worker"


def _background_flag() -> str:
    if is_worker_mode():
        return "off"
    return os.environ.get("BACKGROUND_ON_WEB", "on").strip().lower()


def background_on_web() -> bool:
    """True when web should run any background schedulers (essential or full)."""
    return _background_flag() not in ("0", "false", "no", "off")


def background_heavy_on_web() -> bool:
    """True for legacy combined mode — live subnets + feed warmup on web."""
    flag = _background_flag()
    return flag in ("1", "true", "yes", "on", "full")


def inline_worker_expected() -> bool:
    """True when web machine should host a sibling worker process (Fly v1)."""
    return os.environ.get("INLINE_WORKER", "").strip().lower() in ("1", "true", "yes", "on")


def worker_mode_label() -> str:
    """web | worker | split | combined — for /api/ops/readiness."""
    if is_worker_mode():
        return "worker"
    if inline_worker_expected():
        return "split"
    if background_on_web():
        return "combined"
    return "web"


def background_boot_allowed() -> bool:
    """Skip lifespan/worker boot under pytest or Deploy Guard."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    flag = os.environ.get("DISABLE_BACKGROUND_SCANS", "").strip().lower()
    return flag not in ("1", "true", "yes", "on")
