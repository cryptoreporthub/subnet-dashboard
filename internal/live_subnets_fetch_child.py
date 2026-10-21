"""Minimal spawn entrypoint for live_subnets chain fetch (prod uses spawn context).

Keeps the multiprocessing child import surface small — do not import server or live_subnets
parent module here (spawn would re-exec and pickle through live_subnets otherwise).
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Any, List

logger = logging.getLogger("live_subnets_fetch_child")


def _registry_netuids() -> List[int]:
    import json

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "config", "registry.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            reg = json.load(f)
    except Exception:
        return []
    rows = reg.get("subnets") if isinstance(reg, dict) and isinstance(reg.get("subnets"), list) else []
    if not rows and isinstance(reg, dict):
        rows = list(reg.values())
    out: List[int] = []
    for rec in rows:
        if not isinstance(rec, dict):
            continue
        for k in ("netuid", "id", "subnet_id"):
            v = rec.get(k)
            if isinstance(v, int):
                out.append(v)
                break
            if isinstance(v, str) and v.isdigit():
                out.append(int(v))
                break
    return sorted(set(out))


def _row_netuid(row: dict[str, Any]) -> int | None:
    for key in ("netuid", "id", "subnet_id"):
        val = row.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None


def resolve_fetch_netuids() -> List[int]:
    """Pinned chain IDs for this fetch (before RPC)."""
    test_requested = os.environ.get("LIVE_SUBNETS_TEST_REQUESTED_NETUIDS", "").strip()
    if test_requested:
        import json

        parsed = json.loads(test_requested)
        if isinstance(parsed, list):
            return sorted({int(n) for n in parsed})
    try:
        from internal.subnet_universe import get_netuids

        netuids = get_netuids()
    except Exception:
        netuids = []
    if not netuids:
        netuids = _registry_netuids()
    return sorted({int(n) for n in netuids})


def fetch_meta_from_batch(
    requested_netuids: List[int],
    rows: List[dict[str, Any]],
    *,
    batch_expired: bool,
    netuid_outcomes: dict[int, str],
) -> dict[str, Any]:
    completed = sorted(
        {n for n in (_row_netuid(r) for r in rows) if n is not None}
    )
    missing = [n for n in requested_netuids if n not in set(completed)]
    refresh_complete = not missing
    if refresh_complete:
        degraded_reason = None
    elif any(netuid_outcomes.get(n) == "batch_expired" for n in missing):
        degraded_reason = "batch_deadline"
    else:
        degraded_reason = "fetch_errors"
    return {
        "requested_netuids": list(requested_netuids),
        "completed_netuids": completed,
        "missing_netuids": missing,
        "refresh_complete": refresh_complete,
        "degraded_reason": degraded_reason,
        "batch_expired": batch_expired,
        "netuid_outcomes": {int(k): str(v) for k, v in netuid_outcomes.items()},
    }


def collect_chain_rows() -> tuple[List[dict[str, Any]], List[int], dict[str, Any]]:
    """Blocking RPC fetch; chain_client uses per-request socket timeouts."""
    setup_sleep = os.environ.get("LIVE_SUBNETS_CHILD_SETUP_SLEEP_SECONDS", "").strip()
    if setup_sleep:
        import time

        time.sleep(float(setup_sleep))

    sleep_s = os.environ.get("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "").strip()
    if sleep_s:
        import time

        time.sleep(float(sleep_s))

    requested = resolve_fetch_netuids()
    test_rows = os.environ.get("LIVE_SUBNETS_TEST_ROWS_JSON")
    if test_rows:
        import json

        parsed = json.loads(test_rows)
        rows = parsed if isinstance(parsed, list) else []
        outcomes: dict[int, str] = {}
        for row in rows:
            n = _row_netuid(row)
            if n is not None:
                outcomes[int(n)] = "ok"
        for n in requested:
            outcomes.setdefault(int(n), "no_price")
        meta = fetch_meta_from_batch(
            requested,
            rows,
            batch_expired=False,
            netuid_outcomes=outcomes,
        )
        return rows, requested, meta

    from internal.chain_client import get_default_client

    client = get_default_client()
    mode = os.environ.get("LIVE_SUBNETS_FETCH_MODE", "lite").strip().lower()
    if mode in ("lite", "price"):
        if hasattr(client, "get_subnet_price_rows_batch"):
            batch = client.get_subnet_price_rows_batch(requested)
        else:
            rows = client.get_subnet_price_rows(requested)
            outcomes: dict[int, str] = {}
            for row in rows:
                n = _row_netuid(row)
                if n is not None:
                    outcomes[int(n)] = "ok"
            for n in requested:
                outcomes.setdefault(int(n), "no_price")
            batch = {
                "rows": rows,
                "batch_expired": False,
                "netuid_outcomes": outcomes,
            }
        meta = fetch_meta_from_batch(
            requested,
            batch["rows"],
            batch_expired=bool(batch.get("batch_expired")),
            netuid_outcomes=dict(batch.get("netuid_outcomes") or {}),
        )
        return batch["rows"], requested, meta
    rows = client.get_all_subnet_data(netuids=requested or None)
    outcomes = {int(n): "ok" for n in (_row_netuid(r) for r in rows) if n is not None}
    for n in requested:
        if int(n) not in outcomes:
            outcomes[int(n)] = "fetch_errors"
    meta = fetch_meta_from_batch(
        requested,
        rows,
        batch_expired=False,
        netuid_outcomes=outcomes,
    )
    return rows, requested, meta


def _rpc_return_margin_seconds() -> float:
    """Reserve parent RPC window for executor shutdown + framed result send."""
    raw = os.environ.get("LIVE_SUBNETS_RPC_RETURN_MARGIN_SECONDS", "3").strip()
    try:
        margin = float(raw)
    except ValueError:
        margin = 3.0
    return max(0.5, margin)


def _child_send_deadline() -> float:
    import time

    raw = os.environ.get("LIVE_SUBNETS_CHILD_SEND_DEADLINE_SECONDS", "").strip()
    seconds = float(raw) if raw else 60.0
    return time.monotonic() + seconds


def _send_child_frame(conn, payload: dict[str, Any], *, deadline: float) -> bool:
    from internal.live_subnets_ipc import _MAX_PAYLOAD, send_framed_body, send_message

    try:
        body = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        logger.warning("live_subnets fetch child: pickle failed: %s", exc)
        send_message(conn, {"ok": False, "exc": "pickle_failed"}, deadline=deadline)
        return False
    if len(body) > _MAX_PAYLOAD:
        logger.warning(
            "live_subnets fetch child: payload %d bytes exceeds max %d",
            len(body),
            _MAX_PAYLOAD,
        )
        send_message(conn, {"ok": False, "exc": "payload_too_large"}, deadline=deadline)
        return False
    if send_framed_body(conn, body, deadline=deadline):
        return True
    logger.warning(
        "live_subnets fetch child: send failed (%s)",
        payload.get("phase") or "result",
    )
    return False


def run_fetch_child(conn) -> None:
    import time

    os.environ["LIVE_SUBNETS_FETCH_CHILD"] = "1"
    try:
        from internal.app_logging import configure_app_logging

        configure_app_logging()
    except Exception:
        pass

    from internal.live_subnets_ipc import send_message
    try:
        from internal.process_memory import set_linux_process_comm

        set_linux_process_comm("live-subnets-fetch")
    except Exception:
        pass
    params: dict[str, Any] | None = None
    try:
        ready_sleep = os.environ.get("LIVE_SUBNETS_CHILD_READY_SLEEP_SECONDS", "").strip()
        if ready_sleep:
            time.sleep(float(ready_sleep))
        from internal.live_subnets_ipc import recv_message

        if not _send_child_frame(conn, {"phase": "ready"}, deadline=_child_send_deadline()):
            return
        params = recv_message(conn, time.monotonic() + 5.0)
        if not isinstance(params, dict) or params.get("rpc_deadline_monotonic") is None:
            return
        rpc_deadline = float(params["rpc_deadline_monotonic"])
        batch_deadline = rpc_deadline - _rpc_return_margin_seconds()
        if batch_deadline <= time.monotonic():
            batch_deadline = time.monotonic() + 0.01
        os.environ["LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC"] = str(batch_deadline)
        try:
            data, requested, meta = collect_chain_rows()
        finally:
            os.environ.pop("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", None)
        _send_child_frame(
            conn,
            {"ok": True, "data": data, **meta},
            deadline=rpc_deadline,
        )
    except Exception as exc:
        send_deadline = _child_send_deadline()
        if isinstance(params, dict) and params.get("rpc_deadline_monotonic") is not None:
            send_deadline = float(params["rpc_deadline_monotonic"])
        _send_child_frame(conn, {"ok": False, "exc": str(exc)}, deadline=send_deadline)
    finally:
        try:
            conn.close()
        except Exception:
            pass
