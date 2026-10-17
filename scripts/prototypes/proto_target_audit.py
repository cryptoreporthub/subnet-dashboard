"""Prototype: the grading target. What does sign-only grading of always-long picks measure, and what would a market-relative
target need that the ledger does not store?

Sections
  A  noise floor of a sign target (how many 1h rows are decided by a sub-0.05% tick)
  B  baseline-free skill test using only what the ledger has: council signal-bullish picks (published, direction up) vs the
     signal-bearish HOLD counterfactuals (council_shadow, direction down), same pipeline, same hours
  C  common-factor share: ledger hits clustered by day (intra-class correlation, design effect) and, from the committed
     7-day / 129-subnet candle cache, the share of a single name's hourly return explained by the cross-sectional mean
  D  power: days/labels needed to detect a +5pt hit-rate edge under (i) the current design (about 6 picks per day, one shared
     market factor) vs (ii) a universe-wide excess-return label (every scored name, demeaned each hour)
  E  what the same published rows look like against a crude same-day baseline (ledger-only, low reliability)
Limits are printed with the numbers. Run: /usr/bin/python3 scripts/prototypes/proto_target_audit.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _universe as U
import _wf as W

df = L.load()
c = df[df["pop"].isin(["council_published", "council_shadow"]) & (df.h == 1)].copy()
c["up"] = (c.act > 0).astype(int)
pub, sh = c[c["pop"] == "council_published"], c[c["pop"] == "council_shadow"]

print("A  NOISE FLOOR OF A SIGN TARGET (council 1h rows)")
for thr in (0.05, 0.1, 0.25, 0.5):
    print(f"   |return| < {thr:4.2f}%: {np.mean(c.act.abs() < thr):.3f} of rows (these are graded hit/miss by the sign of a tick)")
dec = pub[pub.act.abs() >= 0.25]
e, lo, hi = W.day_boot(dec[["day", "up"]], lambda x: x.up.mean())
print(f"   published hit rate on decisive moves only (|r|>=0.25%): {e:.3f} [{lo:.3f},{hi:.3f}] n={len(dec)}  (all rows: {pub.up.mean():.3f})")

print("\nB  BASELINE-FREE SKILL TEST: bullish council signal vs bearish council signal")
print(f"   published (signal bullish, n={len(pub)}) up-rate {pub.up.mean():.3f} mean return {pub.act.mean():+.3f}% median {pub.act.median():+.3f}%")
print(f"   shadow    (signal bearish, n={len(sh)}) up-rate {sh.up.mean():.3f} mean return {sh.act.mean():+.3f}% median {sh.act.median():+.3f}%")
cc = c.assign(pubf=(c["pop"] == "council_published").astype(int))
sp_up = lambda x: x[x.pubf == 1].up.mean() - x[x.pubf == 0].up.mean() if (x.pubf == 1).any() and (x.pubf == 0).any() else np.nan
sp_ret = lambda x: x[x.pubf == 1].act.mean() - x[x.pubf == 0].act.mean() if (x.pubf == 1).any() and (x.pubf == 0).any() else np.nan
for nm, f in (("up-rate spread", sp_up), ("mean-return spread (pct points)", sp_ret)):
    e, lo, hi = W.day_boot(cc[["day", "pubf", "up", "act"]], f)
    print(f"   {nm}: {e:+.3f}  day-cluster 95% CI [{lo:+.3f},{hi:+.3f}]   (skill would be > 0)")
print("   caveat: shadow rows exist only on HOLD days for the best-scored candidate, so the two groups are not drawn from the same hours.")

print("\nC  COMMON FACTOR")
a1 = df[df.h == 1].copy()
a1["up"] = (a1.act > 0).astype(int)
g = a1.groupby("day").up
k = g.size()
grand = a1.up.mean()
msb = (k * (g.mean() - grand) ** 2).sum() / (len(k) - 1)
msw = ((a1.up - g.transform("mean")) ** 2).sum() / (len(a1) - len(k))
m0 = (len(a1) - (k ** 2).sum() / len(a1)) / (len(k) - 1)
icc = (msb - msw) / (msb + (m0 - 1) * msw)
print(f"   ledger, all clean 1h rows ({len(a1)} on {len(k)} days): ANOVA ICC of 'up' within day = {icc:.3f}; design effect for the council rows below uses their own cluster size")
C, V, H, Lw = U.load_panel()
R = U.forward_returns(C, 1).iloc[:-1]
R = R.loc[:, R.notna().mean() > 0.8]
cs = R.sub(R.median(axis=1), axis=0)
ss_tot = ((R - R.stack().mean()) ** 2).sum().sum()
ss_res = (cs ** 2).sum().sum()
print(f"   candle cache ({R.shape[1]} subnets x {R.shape[0]} hours, USD-scaled TMC candles Jul31-Aug7): one common series (the same-hour cross-sectional median) explains {1-ss_res/ss_tot:.2%} of single-name hourly return variance")
print(f"   candle hourly return sd {R.stack().std():.2f}% vs {c.act.std():.2f}% in the live_oracle ledger rows. DATA-QUALITY FINDING, not a market fact: a grading path that reads these candles measures TAO/USD,")
print("   not subnet performance (Ditto 2026-10-12: TMC rescales history by TAO/USD). Ledger rows priced by live_oracle are not that series. Any universe reference (FX1) must be stored in ONE unit (alpha-per-TAO).")

print("\nD  POWER (80% power, two-sided 5%): detect a true hit-rate edge of +5 points")
p0, edge = 0.5, 0.05
pub_per_day = len(pub) / pub.day.nunique()
rho = max(icc, 0.0)
m = pub_per_day
deff = 1 + (m - 1) * rho
n_ind = ((1.96 + 0.84) ** 2 * (p0 * (1 - p0) * 2)) / edge ** 2  # two-sample style, both arms ~ p0
n_ind_one = ((1.96 * np.sqrt(p0 * (1 - p0)) + 0.84 * np.sqrt((p0 + edge) * (1 - p0 - edge))) / edge) ** 2
print(f"   independent-row sample size for one arm vs 0.50: {n_ind_one:.0f} rows; with design effect {deff:.2f} (rho={rho:.3f}, ~{m:.1f} picks/day) -> {n_ind_one*deff:.0f} rows = {n_ind_one*deff/m:.0f} days at today's pick rate")
print(f"   the ledger has {len(pub)} published 1h rows on {pub.day.nunique()} days; observed day-clustered CI half-width on the hit rate is about 0.065 (min detectable edge ~ +-0.065..0.09)")
names, hrs = 165, 24
print(f"   universe-wide excess label: {names} names x {hrs} hours = {names*hrs} labels/day, demeaned each hour (rho ~ 0 for the common factor). "
      f"Even if residual cross-correlation leaves ~10 effective names/hour, that is {10*hrs} labels/day vs {m:.1f} -> the same edge is detectable in about {n_ind_one/(10*hrs):.1f} days instead of {n_ind_one*deff/m:.0f}.")

print("\nE  crude same-day baseline (ledger rows only; a stand-in, NOT the FX1 universe median)")
c2 = c.copy()
c2["dm"] = c2.act - c2.groupby("day").act.transform("median")
p2 = c2[c2["pop"] == "council_published"]
e, lo, hi = W.day_boot(p2.assign(x=(p2.dm > 0).astype(int))[["day", "x"]], lambda x: x.x.mean())
print(f"   published hit vs same-day council-row median: {e:.3f} [{lo:.3f},{hi:.3f}] n={len(p2)} (rows/day is small, so this baseline is itself noisy)")
