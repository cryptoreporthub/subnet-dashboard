"""Prototype: universe selection -- the 20/24/40/75 caps and snapshot-rank slicing.

Part 1 (ledger, what the picks actually covered): concentration of published picks across netuids, and which market-cap
        ranks they came from (rank taken from the 2026-10-17 prod cross-section; approximate for earlier dates).
Part 2 (simulation of the production selection loop, re-implemented from source, line refs in comments):
  internal/subnets/scoring_cap.py:91-123  cap_subnets_for_scoring: if a fresh snapshot exists -> rank_subnets_by_snapshot()[:cap];
                                          else heuristic pool (market-cap rank > 10, mid band 11-75 first, then activity).
  internal/council/score_snapshots.py:233-266  rank key = (snapshot score or -1.0, emission): names the snapshot did not score get -1.
  internal/council/score_snapshots.py:131-160  save_score_snapshot REPLACES the file (no merge): the next snapshot contains only the names just scored.
  Result to test: the scored set is an absorbing state -- once 40 names are scored, 40 names outrank everything unscored,
  so the same 40 are re-selected every cycle and the other 125 are never scored (until the snapshot goes stale -> heuristic pool again).
Compared with (b) score every tradable name each cycle (cost measured by proto_scoring_cost.py), and (c) a rotating cap.

Run: /usr/bin/python3 scripts/prototypes/proto_universe_selection.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ledger as L

fx = json.load(open(os.path.join(HERE, "fixtures", "scores_2026-10-17.json")))
N = len(fx)
nets = sorted(fx, key=int)
print(f"cross-section: {N} tradable subnets (prod /api/subnets 2026-10-17); product day scores from score_subnet_for_day")
mcr = {n: (fx[n]["marketcap_rank"] or 10_000) for n in nets}

# ---------------- Part 1: ledger coverage
pub = L.load(populations=["council_published"])
cnt = pub.groupby("netuid").size().sort_values(ascending=False)
p = cnt / cnt.sum()
print(f"\nPART 1  published council picks (clean): {len(pub)} rows on {pub.day.nunique()} days")
print(f"  distinct netuids picked: {len(cnt)} of {N} ({100*len(cnt)/N:.0f}% of the universe); effective number of names 1/HHI = {1/np.sum(p**2):.1f}; top-3 share = {p.head(3).sum():.2f}")
ranks = pd.Series({n: mcr.get(str(n)) for n in cnt.index}).dropna()
print(f"  market-cap-rank of picked names (current rank): min {int(ranks.min())}, median {int(ranks.median())}, max {int(ranks.max())}; picks with rank <= 10: {int((ranks<=10).sum())} names")
allp = L.load()
print(f"  all-population rows (picks + shadow + pump) cover {allp.netuid.nunique()} distinct netuids")

# ---------------- Part 2: absorbing-state simulation
rng = np.random.default_rng(5)
base = np.array([fx[n]["score"] for n in nets], dtype=float)
emission = np.array([fx[n]["emission"] or 0 for n in nets], dtype=float)
vol = np.array([fx[n]["volume"] or 0 for n in nets], dtype=float)
mcap = np.array([fx[n]["market_cap"] or 0 for n in nets], dtype=float)
mrank = np.array([mcr[n] for n in nets])
CAP, MEGA, MID_LO, MID_HI = 40, 10, 11, 75


def heuristic_pool(cap):
    # scoring_cap._heuristic_hunt_pool: skip rank<=10; tier 3 = rank in 11..75, tier 2 = rest; then activity (vol, mcap, rank bonus, emission)
    idx = [i for i in range(N) if mrank[i] > MEGA]
    tier = lambda i: 3 if MID_LO <= mrank[i] <= MID_HI else 2
    idx.sort(key=lambda i: (tier(i), 1 if (vol[i] > 0 or mcap[i] > 0) else 0, vol[i], mcap[i], -mrank[i], emission[i]), reverse=True)
    return idx[:cap]


def simulate(policy, cycles=200, cap=CAP, phi=0.9, sigma=3.0, stale_every=None):
    """true score_t = base + AR(1) drift; the policy decides which indices get scored each cycle."""
    drift = np.zeros(N)
    snapshot = None  # dict idx -> score
    scored_ever, mega_scored, jacc, prev = set(), set(), [], None
    sizes = []
    for t in range(cycles):
        drift = phi * drift + rng.normal(0, sigma, N) * np.sqrt(1 - phi ** 2)
        true = base + drift
        if policy == "full":
            sel = list(range(N))
        elif policy == "rotating":
            sel = [(t * cap + k) % N for k in range(cap)]
        else:  # production
            stale = stale_every is not None and t % stale_every == 0
            if snapshot is None or stale:
                sel = heuristic_pool(cap)
            else:
                order = sorted(range(N), key=lambda i: (snapshot.get(i, -1.0), emission[i]), reverse=True)
                sel = order[:cap]
        snapshot = {i: float(true[i]) for i in sel}  # wholesale replacement
        scored_ever.update(sel)
        if mrank_any := [i for i in sel if mrank[i] <= MEGA]:
            mega_scored.update(mrank_any)
        if prev is not None:
            jacc.append(len(prev & set(sel)) / len(prev | set(sel)))
        prev = set(sel)
        sizes.append(len(sel))
    # structural metrics only: they do not depend on the fixture's scores (the fixture's technicals are partly stale)
    return {"distinct_names_ever_scored": len(scored_ever), "mean_overlap_with_previous_cycle": float(np.mean(jacc)),
            "mega_names_ever_scored": len(mega_scored), "mean_names_scored_per_cycle": float(np.mean(sizes))}


print("\nPART 2  200 cycles, AR(1) score drift (phi .9, sd 3 pts) around the real 2026-10-17 scores")
rows = []
for name, kw in (("production: snapshot-rank cap 40", dict(policy="prod")), ("production, snapshot refreshed from heuristic every 12 cycles", dict(policy="prod", stale_every=12)),
                 ("production pick path: cap 20", dict(policy="prod", cap=20)), ("rotating cap 40 (no feedback)", dict(policy="rotating")), ("full universe each cycle", dict(policy="full"))):
    r = simulate(**kw)
    r["policy"] = name
    rows.append(r)
res = pd.DataFrame(rows).set_index("policy")
pd.set_option("display.width", 220)
print(res.round(2).to_string())
mega_n = int((mrank <= MEGA).sum())
print(f"\n  market-cap rank <= {MEGA} names in the universe: {mega_n}; the heuristic pool excludes them and a snapshot cannot rank what it never scored,")
print("  so under the production loop they are unreachable WHILE THE SNAPSHOT IS FRESH (< SCORE_SNAPSHOT_MAX_AGE_SECONDS=7200 s); on a stale/missing snapshot the heuristic pool is used instead.")
print("  The ledger shows 2 picked names with CURRENT market-cap rank <= 10: rank drift over the window or stale-snapshot cycles are both possible; the mechanism was not isolated.")
print("  Prod evidence for the closed set: /api/learning/health score_snapshot on 2026-10-17 reported count 40, capped_out 125, selection_policy rank_cap (report FX F48).")


# ---------------- Part 3: does production actually behave like the absorbing-state model?  (challenge to Part 2)
ab = json.load(open(os.path.join(HERE, "fixtures", "council_ab_2026-10-17.json")))
S = sorted(ab["snapshots"], key=lambda r: r["captured_at"])
sets = [frozenset(r["universe_netuids"]) for r in S]
jac = [len(a & b) / len(a | b) for a, b in zip(sets, sets[1:])]
union = set().union(*sets)
print(f"\nPART 3  prod A/B record, the 20-name pick universe in {len(S)} snapshots {S[0]['captured_at'][:10]}..{S[-1]['captured_at'][:10]}:")
print(f"  distinct universes {len(set(sets))}; union of names {len(union)} of {N} ({100*len(union)/N:.0f}%); names present in every snapshot {len(frozenset.intersection(*sets))};"
      f" consecutive-snapshot overlap (Jaccard) mean {np.mean(jac):.2f}, min {np.min(jac):.2f}")
print("  => production is NOT strictly absorbing (the set churns, probably through the stale-snapshot -> heuristic-pool path and feed gaps), but it covers about a third of the universe in")
print("     two weeks and is sticky (0.79 overlap per 3h). Part 2 is the mechanism; Part 3 is the size of the effect. The leak path was not isolated.")
