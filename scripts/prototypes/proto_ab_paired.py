"""Prototype: evaluate the council's rankers on the ONLY paired, pre-registered record the system keeps: council_ab_benchmark.

internal/council/ab_benchmark.py records, every 3h, the top-5 of the Daily Model and of the Judge Council ranking over the SAME
20-name universe, then settles each entry 24h later. That is the right shape for a ranker evaluation (paired, immutable, same
universe). This script (a) audits the settlement, (b) runs the paired comparison on the clean part, (c) tests whether score/rank/judge
scores order 24h returns, (d) says what the record still lacks (universe prices -> no excess return).

Data: GET /api/council-ab?limit=90 (read-only; the route caps at the latest 90 of 321 snapshots), committed at
scripts/prototypes/fixtures/council_ab_2026-10-17.json.  Run: /usr/bin/python3 scripts/prototypes/proto_ab_paired.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _wf as W

d = json.load(open(os.environ.get("AB_JSON", os.path.join(HERE, "fixtures", "council_ab_2026-10-17.json"))))
rows = []
for s in d["snapshots"]:
    for lst in ("daily_model", "judge_council"):
        for e in s.get(lst) or []:
            js = e.get("judge_scores") or {}
            rows.append({"slot": s["observation_slot"], "day": s["observation_slot"][:10], "list": lst, "netuid": e["netuid"], "rank": e["rank"], "score": e["score"],
                         "entry": e["entry_price"], "exit": e.get("exit_price"), "ret": e.get("return_pct"), "oracle": js.get("oracle"), "echo": js.get("echo"), "pulse": js.get("pulse")})
df = pd.DataFrame(rows)
st = df[df.ret.notna()].copy()
st["flat"] = (st.exit == st.entry)
print(f"retrieved {df.slot.nunique()} of {d['snapshot_count']} snapshots ({df.slot.min()[:10]}..{df.slot.max()[:10]}); settled entries {len(st)}")

print("\n(a) SETTLEMENT AUDIT -- entries whose exit price equals the entry price exactly (a stale feed, graded 'miss')")
g = st.groupby("day").agg(entries=("flat", "size"), exit_eq_entry=("flat", "mean"))
print(g.round(2).T.to_string())
tot_flat = st.flat.mean()
print(f"  {tot_flat:.1%} of all settled entries are exit==entry. Published scorecard (all entries): daily_model hit {d['daily_model']['hit_rate']}, judge_council hit {d['judge_council']['hit_rate']}")
for lst, g2 in st.groupby("list"):
    clean = g2[~g2.flat]
    print(f"  {lst:14s} all: hit {np.mean(g2.ret > 0):.3f} mean ret {g2.ret.mean():+.3f}% | excluding exit==entry: n={len(clean)} hit {np.mean(clean.ret > 0):.3f} mean ret {clean.ret.mean():+.3f}%")

# clean slots: those with no exit==entry entries
bad_slots = set(st[st.flat].slot)
cl = st[~st.slot.isin(bad_slots)].copy()
print(f"\n(b) PAIRED COMPARISON on {cl.slot.nunique()} clean slots ({cl.day.nunique()} days): Daily Model top-5 vs Judge Council top-5 on the same 20-name universe")
p = cl.groupby(["slot", "day", "list"]).ret.mean().unstack().dropna().reset_index()
p["diff"] = p.daily_model - p.judge_council
e, lo, hi = W.day_boot(p[["day", "diff"]], lambda x: x["diff"].mean())
print(f"  mean 24h return per slot: daily {p.daily_model.mean():+.3f}%  judge {p.judge_council.mean():+.3f}%  paired diff (daily - judge) {e:+.3f}% day-cluster CI [{lo:+.3f},{hi:+.3f}]")
for lst in ("daily_model", "judge_council"):
    q = cl[cl["list"] == lst].assign(up=lambda x: (x.ret > 0).astype(int))
    e, lo, hi = W.day_boot(q[["day", "up"]], lambda x: x.up.mean())
    em, lm, hm = W.day_boot(q[["day", "ret"]], lambda x: x.ret.mean())
    print(f"  {lst:14s} hit {e:.3f} [{lo:.3f},{hi:.3f}]  mean return {em:+.3f}% [{lm:+.3f},{hm:+.3f}]  (n={len(q)}; always-long, 24h: market drift dominates)")
ov = []
for slot, g3 in cl.groupby("slot"):
    a, b = set(g3[g3["list"] == "daily_model"].netuid), set(g3[g3["list"] == "judge_council"].netuid)
    ov.append(len(a & b) / max(1, len(a | b)))
print(f"  Jaccard overlap of the two top-5 lists, mean {np.mean(ov):.2f} (1.0 = same names)")

# --- beta check: is the daily-vs-judge spread just market exposure?  (all clean slots were down days)
snap_ctx = {s_["observation_slot"]: (s_.get("market_context") or {}).get("tao_change_24h") for s_ in d["snapshots"]}
p["tao24"] = p.slot.map(snap_ctx)
p["union"] = (p.daily_model + p.judge_council) / 2.0
print(f"\n  BETA CHECK (spread = daily - judge per slot, n={len(p)} slots)")
print(f"   mean union return {p.union.mean():+.2f}%  share of slots with union return < 0: {(p.union < 0).mean():.2f}; tao_change_24h at entry mean {p.tao24.mean():+.2f}%")
lo_m, hi_m = p[p.union <= p.union.median()], p[p.union > p.union.median()]
print(f"   spread when the union lost more (n={len(lo_m)}): {lo_m['diff'].mean():+.2f}%   when it lost less / gained (n={len(hi_m)}): {hi_m['diff'].mean():+.2f}%")
b = np.polyfit(p.union.values, p["diff"].values, 1)
e, lo, hi = W.day_boot(p[["day", "union", "diff"]], lambda x: np.polyfit(x.union.values, x["diff"].values, 1)[0] if x.union.nunique() > 2 else np.nan)
print(f"   slope of spread on union return = {e:+.3f} [{lo:+.3f},{hi:+.3f}]; intercept (spread at zero market move) = {b[1]:+.3f}%  <- if the slope is large and the intercept ~0 the spread is beta, not selection")
e, lo, hi = W.day_boot(p[["day", "tao24", "diff"]].dropna(), lambda x: x.tao24.corr(x["diff"]))
print(f"   corr(spread, ex-ante tao_change_24h) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]")
# thinness proxy: current market-cap rank of the names each ranker holds (approximate: 2026-10-17 ranks applied to Oct 3-17 entries)
try:
    fx = json.load(open(os.path.join(HERE, "fixtures", "subnets_2026-10-17.json")))["subnets"]
    mc = {int(r_["netuid"]): r_.get("marketcap_rank") for r_ in fx if r_.get("netuid") is not None}
    cl["mcrank"] = cl.netuid.map(mc)
    print("   mean current market-cap rank of held names: " + ", ".join(f"{k}={v:.0f}" for k, v in cl.groupby("list").mcrank.mean().items()) + " (higher number = smaller cap)")
except Exception as exc:  # fixture optional
    print("   market-cap rank check skipped:", exc)

print("\n(c) DO SCORES ORDER 24h RETURNS? (clean slots; Spearman, day-cluster CI)")
for lst in ("daily_model", "judge_council"):
    q = cl[cl["list"] == lst]
    for col in ("score", "rank"):
        e, lo, hi = W.day_boot(q[["day", col, "ret"]], lambda x, c=col: x[c].rank().corr(x["ret"].rank()))
        print(f"  {lst:14s} IC({col}, 24h return) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]  n={len(q)}")
q = cl[cl["list"] == "judge_council"].dropna(subset=["oracle", "echo", "pulse"])
for col in ("oracle", "echo", "pulse"):
    e, lo, hi = W.day_boot(q[["day", col, "ret"]], lambda x, c=col: x[c].rank().corr(x["ret"].rank()))
    print(f"  judge {col:7s} IC(24h return) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]")
print("\n(d) WHAT IS MISSING: prices of the other ~15 universe names at entry and exit. Without them there is no same-window universe median, so excess")
print("    return and rank-skill-vs-universe cannot be computed; capture `universe_prices` (netuid -> typed price) in each snapshot and at settlement.")
