"""Minimal spawn entrypoint for live_subnets chain fetch (prod uses spawn context).

Keeps the multiprocessing child import surface small — do not import server or live_subnets
parent module here (spawn would re-exec and pickle through live_subnets otherwise).
"""
from __future__ import annotations

import os
from typing import Any, List


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


def collect_chain_rows() -> List[dict[str, Any]]:
    """Blocking RPC fetch; chain_client uses per-request socket timeouts."""
    sleep_s = os.environ.get("LIVE_SUBNETS_CHILD_RPC_SLEEP_SECONDS", "").strip()
    if sleep_s:
        import time

        time.sleep(float(sleep_s))

    test_rows = os.environ.get("LIVE_SUBNETS_TEST_ROWS_JSON")
    if test_rows:
        import json

        parsed = json.loads(test_rows)
        return parsed if isinstance(parsed, list) else []

    from internal.chain_client import get_default_client

    client = get_default_client()
    try:
        from internal.subnet_universe import get_netuids

        netuids = get_netuids()
    except Exception:
        netuids = []
    if not netuids:
        netuids = _registry_netuids()
    mode = os.environ.get("LIVE_SUBNETS_FETCH_MODE", "lite").strip().lower()
    if mode in ("lite", "price"):
        return client.get_subnet_price_rows(netuids)
    return client.get_all_subnet_data(netuids=netuids or None)


def _child_send_deadline() -> float:
    import time

    raw = os.environ.get("LIVE_SUBNETS_CHILD_SEND_DEADLINE_SECONDS", "").strip()
    seconds = float(raw) if raw else 60.0
    return time.monotonic() + seconds


def run_fetch_child(conn) -> None:
    import time

    from internal.live_subnets_ipc import send_message

    os.environ["LIVE_SUBNETS_FETCH_CHILD"] = "1"
    try:
        ready_sleep = os.environ.get("LIVE_SUBNETS_CHILD_READY_SLEEP_SECONDS", "").strip()
        if ready_sleep:
            time.sleep(float(ready_sleep))
        if not send_message(conn, {"phase": "ready"}, deadline=_child_send_deadline()):
            return
        data = collect_chain_rows()
        send_message(conn, {"ok": True, "data": data}, deadline=_child_send_deadline())
    except Exception as exc:
        send_message(conn, {"ok": False, "exc": str(exc)}, deadline=_child_send_deadline())
    finally:
        try:
            conn.close()
        except Exception:
            pass
