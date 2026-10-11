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


def _child_probe(conn) -> None:
    from internal.live_subnets_fetch_child import run_fetch_child

    # run_fetch_child closes conn; use a wrapper to report peak RSS before RPC.
    peak = _rss_kb()
    conn.send({"phase": "ready", "child_rss_kb_boot": peak})
    try:
        from internal.live_subnets_fetch_child import collect_chain_rows

        t0 = time.monotonic()
        rows = collect_chain_rows()
        rpc_s = time.monotonic() - t0
        peak = max(peak, _rss_kb())
        conn.send(
            {
                "ok": True,
                "rows": len(rows) if rows else 0,
                "child_rss_kb_peak": peak,
                "rpc_seconds": round(rpc_s, 3),
            }
        )
    except Exception as exc:
        conn.send({"ok": False, "exc": str(exc), "child_rss_kb_peak": _rss_kb()})
    finally:
        conn.close()


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("LIVE_SUBNETS_FETCH_MODE", "lite")
    os.environ["PYTHONPATH"] = repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    parent_rss_before = _rss_kb()
    t_start = time.monotonic()
    proc = ctx.Process(target=_child_probe, args=(child_conn,), daemon=True)
    proc.start()
    child_conn.close()
    spawn_to_ready = None
    if parent_conn.poll(60):
        boot = parent_conn.recv()
        spawn_to_ready = time.monotonic() - t_start
    else:
        boot = {"error": "spawn grace timeout"}
    rpc_msg = None
    if isinstance(boot, dict) and boot.get("phase") == "ready" and parent_conn.poll(120):
        rpc_msg = parent_conn.recv()
    proc.join(timeout=5)
    report = {
        "parent_rss_kb_before": parent_rss_before,
        "parent_rss_kb_after": _rss_kb(),
        "spawn_to_ready_s": round(spawn_to_ready or -1, 3),
        "boot": boot,
        "rpc": rpc_msg,
        "child_exitcode": proc.exitcode,
    }
    print(json.dumps(report, indent=2))
    return 0 if rpc_msg and rpc_msg.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
