"""Prototype: score-adjuster ablation -- what CAN be tested from the ledger, and what cannot.

The ledger stores pick_score (the final 0-100 total) and market_impact{relative_flow, sensitivity, strength} +
subnet_snapshot{staking_yield_apy, price_change_24h} for council rows, so three adjusters can be reconstructed exactly
as state_vector.score_subnet_for_day computes them:
    value_boost = clamp((apy - chg24)/100, -0.10, +0.10) * 100          (points)
    flow_boost  = clamp(relative_flow*0.15, -0.05, +0.08) * strength * 100
    size_tilt   = clamp((sensitivity-1)*0.04, -0.06, +0.06) * strength * 100
and scenario_outcome_adjustment (memory) from the ledger itself (per-netuid prior hit rate, +-2 pts).
NOT reconstructable (no per-row field): disposition (+-3), telegram calibration (dormant, enabled=false in prod),
pump overlay (alpha .10, needs ladder state at score time), recovery haircut, red-team multipliers.

For each reconstructable adjuster: information coefficient with the 1h return (day-cluster CI) and a paired ablation
IC(score) vs IC(score without the adjuster). Run:  /usr/bin/python3 scripts/prototypes/proto_adjusters.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _wf as W

df = L.load(populations=["council_published", "council_shadow"])
df = df[df.h == 1].copy().reset_index(drop=True)
mi = df.raw.apply(lambda r: r.get("market_impact") or {})
ss = df.raw.apply(lambda r: r.get("subnet_snapshot") or {})
num = lambda s: pd.to_numeric(s, errors="coerce")
flow, sens, strength = num(mi.apply(lambda m: m.get("relative_flow"))), num(mi.apply(lambda m: m.get("sensitivity"))), num(mi.apply(lambda m: m.get("strength")))
apy, chg24 = num(ss.apply(lambda s: s.get("staking_yield_apy"))), num(ss.apply(lambda s: s.get("price_change_24h"))).fillna(0.0)
# staking_yield_apy is null on most rows (undervalued_score() -> None -> value_gap 0.0 in the product code)
has_apy = apy.notna()
df["value_boost"] = np.where(has_apy, np.clip((apy.fillna(0) - chg24) / 100.0, -0.10, 0.10) * 100, 0.0)
df["has_apy"] = has_apy.values
df["flow_boost"] = np.clip(flow * 0.15, -0.05, 0.08) * strength * 100
df["size_tilt"] = np.clip((sens - 1.0) * 0.04, -0.06, 0.06) * strength * 100
df["strength"] = strength
df["score"] = num(df.score)
df["y"] = (df.act > 0).astype(int)
df["pub"] = (df["pop"] == "council_published").astype(int)
df = df.dropna(subset=["value_boost", "flow_boost", "size_tilt", "score"]).reset_index(drop=True)
df["tilts"] = df.value_boost + df.flow_boost + df.size_tilt
df["score_ex_tilts"] = df.score - df.tilts
print(f"rows={len(df)} days={df.day.nunique()}")
print("\nReconstructed adjuster magnitudes (points on the 0-100 score):")
print(df[["value_boost", "flow_boost", "size_tilt", "tilts", "score"]].describe().round(2).loc[["mean", "std", "min", "max"]].to_string())
print(f"learned impact_strength dial at creation: mean {df.strength.mean():.2f} (default 1.0, hard cap 2.0); share >= 1.9: {(df.strength >= 1.9).mean():.2f}")
print(f"rows with a stored staking_yield_apy: {df.has_apy.mean():.3f} (value tilt is exactly 0 on the rest); share at its +10 clamp: {(df.value_boost >= 9.99).mean():.3f}")

# Day-demeaned return: crude market-factor removal using the ledger's own same-day rows (NOT a universe baseline)
df["act_dm"] = df.act - df.groupby("day").act.transform("mean")


def ic(x, c, r="act"):
    if x[c].nunique() < 2:
        return np.nan
    return x[c].rank().corr(x[r].rank())


print("\nInformation coefficient with 1h return (Spearman), day-cluster 95% CI  [raw return | day-demeaned return]")
for c in ("score", "score_ex_tilts", "tilts", "value_boost", "flow_boost", "size_tilt"):
    e1, l1, h1 = W.day_boot(df[["day", c, "act"]], lambda x, c=c: ic(x, c))
    e2, l2, h2 = W.day_boot(df[["day", c, "act_dm"]], lambda x, c=c: ic(x, c, "act_dm"))
    print(f"  {c:15s} {e1:+.3f} [{l1:+.3f},{h1:+.3f}]  |  {e2:+.3f} [{l2:+.3f},{h2:+.3f}]")

# Paired ablation: does removing the tilts change IC? (difference of ICs, day-cluster)
e, lo, hi = W.day_boot(df[["day", "score", "score_ex_tilts", "act"]], lambda x: ic(x, "score") - ic(x, "score_ex_tilts"))
print(f"\nPaired ablation IC(score) - IC(score without value/flow/size tilts) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]  (positive = tilts help)")

# Memory adjuster (scenario_outcome_adjustment): per-netuid prior published hit rate -> +-2 pts; does it predict the next outcome?
pub = df[df.pub == 1].sort_values("ts").reset_index(drop=True)
adj = []
hist = {}
for _, r in pub.iterrows():
    h = hist.get(r.netuid, [])
    if len(h) >= 2:
        rate = sum(h) / len(h)
        adj.append(float(np.clip((rate - 0.5) * 8.0, -2, 2)))
    else:
        adj.append(0.0)
    hist.setdefault(r.netuid, []).append(int(r.y))
pub["mem_adj"] = adj
act_n = (pub.mem_adj != 0).sum()
print(f"\nMemory adjuster (published rows): active on {act_n}/{len(pub)} rows ({act_n/len(pub):.2f})")
e, lo, hi = W.day_boot(pub[["day", "mem_adj", "y"]], lambda x: x.mem_adj.corr(x.y))
print(f"  corr(memory adjustment, next outcome) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]  (the rule assumes a positive sign)")
a = pub[pub.mem_adj > 0]; b = pub[pub.mem_adj < 0]
print(f"  next up-rate when adj>0: {a.y.mean():.3f} (n={len(a)}); adj<0: {b.y.mean():.3f} (n={len(b)})")
sp = lambda x: x[x.mem_adj > 0].y.mean() - x[x.mem_adj < 0].y.mean() if ((x.mem_adj > 0).any() and (x.mem_adj < 0).any()) else np.nan
e, lo, hi = W.day_boot(pub[["day", "mem_adj", "y"]], sp)
print(f"  spread (adj>0 minus adj<0) = {e:+.3f}  day-cluster CI [{lo:+.3f},{hi:+.3f}]")
e, lo, hi = W.day_boot(pub[["netuid", "mem_adj", "y"]], sp, daycol="netuid")
print(f"  spread with NETUID-cluster bootstrap (same names repeat: {pub.netuid.nunique()} distinct) CI [{lo:+.3f},{hi:+.3f}]")

# Pump overlay proxy: do council picks made while the pump ladder showed an active phase do better?
ph = df.raw.apply(lambda r: r.get("phase_at_prediction"))
df["phase"] = ph.fillna("none")
print("\nPhase at prediction vs 1h up-rate (council rows; the overlay applies to STIRRING/ACCUMULATING/PUMPING/COOLING):")
g = df.groupby("phase").agg(n=("y", "size"), up=("y", "mean"), mean_ret=("act", "mean")).round(3)
print(g.to_string())
stir = df.assign(stir=(df.phase == "STIRRING").astype(int))
e, lo, hi = W.day_boot(stir[["day", "y", "stir"]], lambda x: x[x.stir == 1].y.mean() - x[x.stir == 0].y.mean() if (x.stir == 1).any() and (x.stir == 0).any() else np.nan)
print(f"  up-rate(STIRRING) - up-rate(other phases) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]  day-cluster; STIRRING rows fall on {stir[stir.stir==1].day.nunique()} distinct days")
e, lo, hi = W.day_boot(stir[["day", "act", "stir"]], lambda x: x[x.stir == 1].act.mean() - x[x.stir == 0].act.mean() if (x.stir == 1).any() and (x.stir == 0).any() else np.nan)
print(f"  mean 1h return(STIRRING) - other = {e:+.3f}% [{lo:+.3f},{hi:+.3f}]")
act = df[df.phase.isin(["STIRRING", "ACCUMULATING", "PUMPING", "COOLING"])]
inact = df[~df.phase.isin(["STIRRING", "ACCUMULATING", "PUMPING", "COOLING"])]
if len(act) > 5:
    d = df.assign(active=df.phase.isin(["STIRRING", "ACCUMULATING", "PUMPING", "COOLING"]).astype(int))
    e, lo, hi = W.day_boot(d[["day", "y", "active"]], lambda x: x[x.active == 1].y.mean() - x[x.active == 0].y.mean() if (x.active == 1).any() and (x.active == 0).any() else np.nan)
    print(f"  up-rate(active phase, n={len(act)}) - up-rate(inactive, n={len(inact)}) = {e:+.3f} [{lo:+.3f},{hi:+.3f}]")

# Power: smallest IC detectable (80% power, two-sided 5%) given effective independent days
n_days = df.day.nunique()
rows_per_day = len(df) / n_days
print(f"\nPower: {len(df)} rows on {n_days} days ({rows_per_day:.1f}/day). Day-clustered SE of an IC is about 1/sqrt(days*rows_per_day^0.5...) -- empirically the CIs above are +-0.10 to +-0.15,")
print("so an adjuster capped at +-2..5 points of a 0-100 score cannot be shown to help or hurt unless it moves returns by > ~0.1 IC; the ledger is underpowered for per-adjuster ablation by roughly 10x.")


# ---- STIRRING: exploratory finding -> confound checks (it was found by looking at 5 phases, so treat as a hypothesis)
print("\nSTIRRING robustness (hypothesis, not a finding):")
d2 = df.copy()
d2["stir"] = (d2.phase == "STIRRING").astype(int)
d2["chg24"] = num(d2.raw.apply(lambda r: (r.get("subnet_snapshot") or {}).get("price_change_24h"))).values
d2["chg7"] = num(d2.raw.apply(lambda r: (r.get("subnet_snapshot") or {}).get("price_change_7d"))).values
sp = lambda x: x[x.stir == 1].y.mean() - x[x.stir == 0].y.mean() if ((x.stir == 1).any() and (x.stir == 0).any()) else np.nan
dec = d2[d2.act.abs() >= 0.25]
e, lo, hi = W.day_boot(dec[["day", "y", "stir"]], sp)
print(f"  decisive moves only (|r|>=0.25%, n={len(dec)}): up-rate spread {e:+.3f} [{lo:+.3f},{hi:+.3f}]")
dd = d2.dropna(subset=["chg24", "chg7"]).copy()
print(f"  STIRRING rows carry a recent run-up? mean price_change_24h: STIRRING {dd[dd.stir==1].chg24.mean():+.1f}% vs other {dd[dd.stir==0].chg24.mean():+.1f}%; 7d: {dd[dd.stir==1].chg7.mean():+.1f}% vs {dd[dd.stir==0].chg7.mean():+.1f}%")


def logit_coef(x):
    if x.stir.nunique() < 2 or len(x) < 40:
        return np.nan
    X = np.column_stack([x.stir.values.astype(float), ((x.chg24 - x.chg24.mean()) / (x.chg24.std() + 1e-9)).values, ((x.chg7 - x.chg7.mean()) / (x.chg7.std() + 1e-9)).values])
    return W.fit_logit(X, x.y.values.astype(float), l2=1.0)[1]


e, lo, hi = W.day_boot(dd[["day", "y", "stir", "chg24", "chg7"]], logit_coef)
print(f"  logit(up ~ STIRRING + z(chg24) + z(chg7)): STIRRING coefficient {e:+.3f} [{lo:+.3f},{hi:+.3f}] (log-odds; 0 = no effect once recent momentum is controlled)")
dd["chg24_tercile"] = pd.qcut(dd.chg24, 3, labels=["low", "mid", "high"])
for t, g in dd.groupby("chg24_tercile", observed=True):
    if g.stir.nunique() == 2:
        print(f"  within chg24 tercile {t:4s}: STIRRING up-rate {g[g.stir==1].y.mean():.3f} (n={int(g.stir.sum())}) vs other {g[g.stir==0].y.mean():.3f} (n={int((1-g.stir).sum())})")
def stir_fp(tr, te):
    X, Xt = tr[["stir"]].values.astype(float), te[["stir"]].values.astype(float)
    b = W.fit_logit(X, tr.y.values.astype(float), l2=2.0)
    return {"base": np.full(len(te), np.clip(tr.y.mean(), 0.05, 0.95)), "stirring_flag": W.predict_logit(b, Xt)}


oos = W.walk_forward(d2.reset_index(drop=True), stir_fp)
r = W.compare_to_base(oos, ["stirring_flag"]).iloc[0]
print(f"  walk-forward of a STIRRING flag (_wf protocol): logloss gain {r.logloss_gain_vs_base:+.4f} [{r.ci_lo:+.4f},{r.ci_hi:+.4f}] AUC {r.auc:.3f} n_oos={int(r.n_oos)} -> not confirmed out of sample; pre-register for the universe capture.")


# ---- size_tilt out of sample with the shared protocol (all ICs above are in-sample, except the memory rule which involves no fitting)
def tilt_fp(tr, te):
    out = {"base": np.full(len(te), np.clip(tr.y.mean(), 0.05, 0.95))}
    for nm, col in (("size_tilt", "size_tilt"), ("flow_boost", "flow_boost"), ("score_ex_tilts", "score_ex_tilts")):
        mu, sd = tr[col].mean(), tr[col].std() + 1e-9
        b = W.fit_logit(((tr[col].values - mu) / sd)[:, None], tr.y.values.astype(float), l2=5.0)
        out[nm] = W.predict_logit(b, ((te[col].values - mu) / sd)[:, None])
    return out


oos = W.walk_forward(df.reset_index(drop=True), tilt_fp)
print("\nWalk-forward (Platt of each term on 1h up), logloss gain vs constant:")
print(W.compare_to_base(oos, ["size_tilt", "flow_boost", "score_ex_tilts"]).round(4).to_string(index=False))
print("  (the memory-adjuster test above uses no fitted parameters, so its correlation is already out of sample.)")
