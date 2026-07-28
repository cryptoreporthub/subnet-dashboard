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

        timeout = float(os.environ.get("WORKER_PEER_TIMEOUT_SECONDS", "12"))
        probe_path = os.environ.get("WORKER_PEER_PROBE_PATH", "/api/ops/worker-peer").strip()
        if not probe_path.startswith("/"):
            probe_path = f"/{probe_path}"
        remote = fetch_worker_json_sync(probe_path, timeout=timeout)
        peer = remote.get("worker_peer")
        if isinstance(peer, dict):
            alive = peer.get("alive")
            # Worker machine reports file heartbeat; ignore web misroute (http source).
            if peer.get("source") == "file" and alive is not None:
                return {
                    "expected": True,
                    "alive": bool(alive),
                    "heartbeat": peer.get("heartbeat"),
                    "peer": "dedicated_worker",
                    "source": "http",
                }
    except Exception as exc:
        logger.debug("worker peer HTTP probe failed: %s", exc)
        from internal.worker_proxy import last_worker_probe_error

        detail = last_worker_probe_error() or str(exc)
        return {
            "expected": True,
            "alive": False,
            "peer": "dedicated_worker",
            "source": "http",
            "note": f"worker_http_unreachable: {detail[:200]}",
        }
    return {
        "expected": True,
        "alive": False,
        "peer": "dedicated_worker",
        "source": "http",
        "note": "worker_http_unreachable: unexpected_peer_response",
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
