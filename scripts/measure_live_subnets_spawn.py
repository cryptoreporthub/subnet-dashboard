#!/usr/bin/env python3
"""Measure spawn child RSS + boot timing for live_subnets (run from repo root, venv active)."""
from __future__ import annotations

import json
import multiprocessing
import os
import resource
import sys
import time


def _rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _child_hwm_kb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except Exception:
        return 0
    return 0


def _ensure_registry_netuids(repo_root: str) -> int:
    """Prod child falls back to config/registry.json when universe snapshot is empty."""
    reg_path = os.path.join(repo_root, "config", "registry.json")
    if os.path.isfile(reg_path):
        try:
            with open(reg_path, encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("subnets") if isinstance(data, dict) else []
            if isinstance(rows, list) and rows:
                return len(rows)
        except Exception:
            pass
    from internal.chain_client import get_default_client

    netuids = get_default_client().get_all_netuids()
    if not netuids:
        return 0
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    payload = {"subnets": [{"netuid": n, "name": f"SN{n}"} for n in netuids]}
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return len(netuids)


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["PYTHONPATH"] = repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")
    rpc_wait = float(os.environ.get("LIVE_SUBNETS_MEASURE_RPC_WAIT_SECONDS", "600"))
    registry_n = _ensure_registry_netuids(repo_root)

    from internal.live_subnets_fetch_child import run_fetch_child

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    parent_rss_before = _rss_kb()
    t_start = time.monotonic()
    proc = ctx.Process(target=run_fetch_child, args=(child_conn,), daemon=True)
    proc.start()
    child_conn.close()
    spawn_to_ready = None
    boot = None
    if parent_conn.poll(60):
        boot = parent_conn.recv()
        spawn_to_ready = time.monotonic() - t_start
    else:
        boot = {"error": "spawn grace timeout"}
    child_peak_kb = _child_hwm_kb(proc.pid) if proc.pid else 0
    rpc_msg = None
    rpc_t0 = time.monotonic()
    if isinstance(boot, dict) and boot.get("phase") == "ready":
        while proc.is_alive() and (time.monotonic() - rpc_t0) < rpc_wait:
            child_peak_kb = max(child_peak_kb, _child_hwm_kb(proc.pid))
            if parent_conn.poll(0.5):
                rpc_msg = parent_conn.recv()
                break
        if rpc_msg is None and parent_conn.poll(0):
            rpc_msg = parent_conn.recv()
    proc.join(timeout=5)
    if proc.pid:
        child_peak_kb = max(child_peak_kb, _child_hwm_kb(proc.pid))
    parent_after = _rss_kb()
    report = {
        "fetch_mode": mode,
        "registry_netuids": registry_n,
        "parent_rss_kb_before": parent_rss_before,
        "parent_rss_kb_after": parent_after,
        "child_rss_kb_peak": child_peak_kb,
        "combined_rss_kb_estimate": parent_after + child_peak_kb,
        "spawn_to_ready_s": round(spawn_to_ready or -1, 3),
        "boot": boot,
        "rpc": rpc_msg,
        "child_exitcode": proc.exitcode,
    }
    print(json.dumps(report, indent=2))
    return 0 if isinstance(rpc_msg, dict) and rpc_msg.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
