"""Worker peer liveness — file heartbeat (v1 inline) or HTTP (split v2 web → worker)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _file_peer(*, peer: str, max_age_seconds: int) -> Dict[str, Any]:
    from internal.worker_heartbeat import is_alive, read_heartbeat

    return {
        "expected": True,
        "alive": is_alive(max_age_seconds=max_age_seconds),
        "heartbeat": read_heartbeat(),
        "peer": peer,
        "source": "file",
    }


def _remote_peer(*, max_age_seconds: int) -> Dict[str, Any]:
    """split_v2 web — ask worker machine HTTP for its volume heartbeat."""
    try:
        from internal.worker_proxy import fetch_worker_json_sync

        timeout = float(os.environ.get("WORKER_PEER_TIMEOUT_SECONDS", "6"))
        remote = fetch_worker_json_sync("/api/ops/live", timeout=timeout)
        peer = remote.get("worker_peer")
        if isinstance(peer, dict):
            alive = peer.get("alive")
            if alive is not None:
                return {
                    "expected": True,
                    "alive": bool(alive),
                    "heartbeat": peer.get("heartbeat"),
                    "peer": "dedicated_worker",
                    "source": "http",
                }
    except Exception as exc:
        logger.debug("worker peer HTTP probe failed: %s", exc)
    return {
        "expected": True,
        "alive": False,
        "peer": "dedicated_worker",
        "source": "http",
        "note": "worker_http_unreachable",
    }


def get_worker_peer(*, max_age_seconds: Optional[int] = None) -> Dict[str, Any]:
    """Unified worker_peer dict for readiness, loop_health, and ops/live."""
    from internal.run_mode import inline_worker_expected, is_worker_mode, split_worker_v2_enabled

    age = max_age_seconds if max_age_seconds is not None else 180

    if is_worker_mode():
        return _file_peer(peer="dedicated_worker", max_age_seconds=age)
    if split_worker_v2_enabled():
        return _remote_peer(max_age_seconds=age)
    if inline_worker_expected():
        return _file_peer(peer="inline_worker", max_age_seconds=age)
    return {"expected": False, "alive": None, "peer": "in_process"}
