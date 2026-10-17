"""Prototype: why does scoring cost ~1.3 s per subnet on prod (vs ~2 ms locally), and what removes the need for a count cap?

Mechanism under test (read-only import of product code, nothing is edited):
  state_vector.score_subnet_for_day -> internal.message_intel.calibration.calibration_for_subnet(netuid, conviction_rows=None)
  When the caller's market_context has no `telegram_conviction_rows` (true for score_snapshots.build_full_universe_snapshot;
  only daily_pick.py:118 sets it), EVERY subnet re-runs rollup._conviction_rows(): a LEFT JOIN over messages x message_analysis x
  verdicts x snapshots x outcomes (LIMIT 3000) and then classify_call() on every row twice -- before the `enabled` flag is
  consulted (prod: enabled=false). message_analysis.message_id and price_snapshots.message_id have no index, so the join scans.

Arms (same 165-subnet cross-section pulled read-only from prod /api/subnets, synthetic 3000-message telegram table):
  A_old        market_context={}                             (what the snapshot job does today)
  B_index_only A + CREATE INDEX on the two join columns
  C_hoisted    rows loaded once and passed in telegram_conviction_rows (what daily_pick does)
  D_fixed      B + C + calibration health computed once per cycle and per-netuid evidence from a pre-built index
               (equivalence of D's output to the original function is asserted for every subnet)

Run (needs the repo venv for product imports; pandas not required):
  /home/user/subnet-dashboard/.venv/bin/python scripts/prototypes/proto_scoring_cost.py [--messages 3000] [--subnets 165] [--arms A,B,C,D]
Environment: SUBNETS_JSON=<path to /api/subnets response> (a copy is committed at scripts/prototypes/fixtures/subnets_2026-10-17.json)
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

ap = argparse.ArgumentParser()
ap.add_argument("--messages", type=int, default=3000)
ap.add_argument("--subnets", type=int, default=165)
ap.add_argument("--arms", default="A,B,C,D")
args = ap.parse_args()

work = tempfile.mkdtemp(prefix="proto_scoring_cost_")
os.makedirs(os.path.join(work, "data"))
os.makedirs(os.path.join(work, "config"))
for f in os.listdir(os.path.join(REPO, "config")):
    shutil.copy(os.path.join(REPO, "config", f), os.path.join(work, "config", f))
os.chdir(work)  # product code reads data/... relative to cwd; nothing in the repo is touched

# ---- synthetic telegram table (shape from message_intel/models.py; ~1/3 resolved, 80 authors, 120 subnets)
import random

from message_intel.models import Database

random.seed(3)
db = Database("data/message_intel.db")
with db._connection() as c:
    for i in range(args.messages):
        nu = random.randint(1, 120)
        cur = c.execute(
            "INSERT INTO messages(source,group_id,author_id,author_name,author_username,content,timestamp,created_at,external_message_id) "
            "VALUES('telegram','g',?,?,?,?,?,?,?)",
            (f"a{i%80}", f"n{i%80}", f"u{i%80}", f"SN{nu} looks strong buying more " * 3,
             f"2026-10-{1+i%16:02d}T{i%24:02d}:00:00+00:00", f"2026-10-{1+i%16:02d} {i%24:02d}:00:00", str(i)))
        mid = cur.lastrowid
        c.execute("INSERT INTO message_analysis(message_id,sentiment,entities_json) VALUES(?,?,?)", (mid, "bullish", json.dumps({"netuids": [nu], "subnets": [f"SN{nu}"]})))
        c.execute("INSERT INTO message_verdicts(message_id,verdict,conviction,predicted_direction,predicted_magnitude) VALUES(?,?,?,?,?)", (mid, "BULLISH", random.choice([40, 65, 80]), random.choice(["up", "down"]), 3.0))
        c.execute("INSERT INTO price_snapshots(message_id,tao_usd_price,netuid,snapshot_timestamp) VALUES(?,?,?,?)", (mid, 1.0, nu, "2026-10-01T00:00:00+00:00"))
        if i % 3 == 0:
            c.execute("INSERT INTO price_outcomes(message_id,price_1h,price_4h,price_24h,pump_pct_max,outcome,price_24h_recorded_at) VALUES(?,?,?,?,?,?,?)",
                      (mid, 1.01, 1.02, 1.03, 3.0, random.choice(["hit", "miss"]), "2026-10-17T10:00:00+00:00"))

fixture = os.environ.get("SUBNETS_JSON", os.path.join(HERE, "fixtures", "subnets_2026-10-17.json"))
subs = [s for s in json.load(open(fixture))["subnets"] if s.get("netuid") not in (0, None)][: args.subnets]

from internal.council import state_vector as sv
from internal.message_intel import calibration as cal
from internal.message_intel.rollup import _conviction_rows

sv.score_subnet_for_day(subs[0], {"telegram_conviction_rows": []})  # warm imports
_orig = cal.calibration_for_subnet


def run(label, ctx_fn, patch=None):
    cal.calibration_for_subnet = patch or _orig
    t0 = time.perf_counter()
    out = []
    for s in subs:
        out.append(sv.score_subnet_for_day(s, ctx_fn())["total_score"])
    dt = time.perf_counter() - t0
    print(f"{label:14s} {1000*dt/len(subs):8.1f} ms/subnet   full {len(subs)}-subnet cycle {dt:7.2f} s")
    cal.calibration_for_subnet = _orig
    return dt, out


def add_indexes():
    con = sqlite3.connect("data/message_intel.db")
    con.execute("CREATE INDEX IF NOT EXISTS idx_analysis_message ON message_analysis(message_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_message ON price_snapshots(message_id)")
    con.commit(); con.close()


def make_fixed(rows):
    """D: health once per cycle, per-netuid evidence from an index. Same output contract as calibration_for_subnet."""
    from datetime import datetime, timedelta, timezone

    from internal.message_intel.proof import classify_call, stable_author_id
    from internal.message_intel.rollup import _netuids_from_row, _parse_ts

    health = cal.calibration_health(conviction_rows=rows)
    cfg = cal._config()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg["current_window_hours"])
    by_netuid = {}
    for row in rows:
        proof = classify_call(row)
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if not proof["eligible"] or ts is None or ts < cutoff or proof["direction"] not in {"up", "down"}:
            continue
        for nu in _netuids_from_row(row):
            by_netuid.setdefault(nu, []).append((row, proof))

    def fast(netuid, *, db=None, now=None, conviction_rows=None):
        try:
            wanted = int(netuid)
        except (TypeError, ValueError):
            return {**health, "applied": False, "adjustment_points": 0.0, "current_evidence": None}
        current = by_netuid.get(wanted, [])
        authors = {stable_author_id(r) for r, _ in current}
        direction_sum = sum(1 if p["direction"] == "up" else -1 for _, p in current)
        direction = "bullish" if direction_sum > 0 else "bearish" if direction_sum < 0 else "mixed"
        reasons = list(health["withheld_reasons"])
        if len(current) < 2 or len(authors) < 2 or direction == "mixed":
            reasons.append("insufficient_current_qualified_consensus")
        applied = health["active"] and "insufficient_current_qualified_consensus" not in reasons
        sign = 1 if direction == "bullish" else -1
        points = 0.0
        if applied:
            edge = max(0.0, float(health["hit_rate"] or 0.0) - 0.5)
            points = round(sign * min(cfg["max_adjustment_points"], edge * 10.0), 2)
        return {**health, "active": applied, "withheld_reasons": reasons, "applied": applied, "adjustment_points": points,
                "current_evidence": {"netuid": wanted, "current_calls": len(current), "contributors": len(authors),
                                     "window_hours": cfg["current_window_hours"], "direction": direction}}
    return fast


arms = args.arms.split(",")
res = {}
print(f"{args.messages} synthetic telegram messages; {len(subs)} subnets from {os.path.basename(fixture)}; cwd={work}")
if "A" in arms:
    res["A"] = run("A_old", lambda: {})
if any(a in arms for a in "BCD"):
    add_indexes()
if "B" in arms:
    res["B"] = run("B_index_only", lambda: {})
t = time.perf_counter(); rows = _conviction_rows(); print(f"  one _conviction_rows() after index: {1000*(time.perf_counter()-t):.1f} ms ({len(rows)} rows)")
if "C" in arms:
    ctx = {"telegram_conviction_rows": rows}
    res["C"] = run("C_hoisted", lambda: ctx)
if "D" in arms:
    t = time.perf_counter(); fast = make_fixed(rows); print(f"  D one-time build (health + per-netuid index): {1000*(time.perf_counter()-t):.1f} ms")
    ctx = {"telegram_conviction_rows": rows}
    res["D"] = run("D_fixed", lambda: ctx, patch=fast)
    # equivalence: D must return the same adjustment contract as the original for every subnet
    bad = 0
    for s in subs:
        a = _orig(s["netuid"], conviction_rows=rows)
        b = fast(s["netuid"])
        if (a["adjustment_points"], a["applied"], sorted(a["withheld_reasons"]), a["current_evidence"]) != (b["adjustment_points"], b["applied"], sorted(b["withheld_reasons"]), b["current_evidence"]):
            bad += 1
    print(f"  D equivalence vs original calibration_for_subnet on {len(subs)} subnets: {len(subs)-bad} identical, {bad} differ")
if "A" in res and "D" in res:
    same = sum(1 for x, y in zip(res["A"][1], res["D"][1]) if abs(x - y) < 1e-9)
    print(f"  total_score identical between A and D on {same}/{len(subs)} subnets (adjuster is disabled in prod so scores must not move)")
    print(f"  speedup A->D: {res['A'][0]/res['D'][0]:.0f}x")
shutil.rmtree(work, ignore_errors=True)
