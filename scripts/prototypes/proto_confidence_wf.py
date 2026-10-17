"""Prototype: confidence / probability architecture, walk-forward on the clean ledger.

Question: does pick_confidence (or pick_score, or the signal-implied move) carry out-of-sample information about
P(1h return > 0)? If not, the only honest probability is the training base rate, and "confidence" must not gate
or weight anything until a model beats that constant out of sample.

Run:  /usr/bin/python3 scripts/prototypes/proto_confidence_wf.py     (pandas+numpy; LEDGER=<path> to override)
Pooling: council_published (direction up) + council_shadow (HOLD counterfactual, mostly direction down), 1h rows.
Target y = 1 if actual_pct > 0 (direction-free, so published and shadow are comparable).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _wf as W

df = L.load(populations=["council_published", "council_shadow"])
df = df[df.h == 1].copy()
df["y"] = (df.act > 0).astype(int)
df["conf"] = df.conf.astype(float)
df["score"] = df.score.astype(float)
df["pred"] = df.pred.astype(float)
df["pub"] = (df["pop"] == "council_published").astype(int)
df = df.dropna(subset=["conf", "score"]).reset_index(drop=True)
print(f"rows={len(df)} days={df.day.nunique()} published={df.pub.sum()} shadow={(1-df.pub).sum()} up-rate={df.y.mean():.3f}")
print(f"conf range {df.conf.min():.3f}-{df.conf.max():.3f}; rows below the 0.40 prod gate: {(df.conf < 0.40).sum()}; below 0.50: {(df.conf < 0.50).sum()}")


def z(a, ref):
    return (a - ref.mean()) / (ref.std() + 1e-9)


def fit_predict(tr, te):
    base = np.full(len(te), np.clip(tr.y.mean(), 0.05, 0.95))
    out = {"base": base}
    ytr = tr.y.values.astype(float)
    # confidence taken at face value: P(up) = confidence (what the UI implies)
    out["conf_as_probability"] = te.conf.values
    for name, cols in {"platt_conf": ["conf"], "platt_score": ["score"], "platt_pred": ["pred"], "platt_conf+score": ["conf", "score"],
                       "direction_flag_only": ["pub"]}.items():
        Xtr = np.column_stack([z(tr[c].values.astype(float), tr[c].values.astype(float)) for c in cols])
        Xte = np.column_stack([z(te[c].values.astype(float), tr[c].values.astype(float)) for c in cols])
        beta = W.fit_logit(Xtr, ytr, l2=5.0)
        out[name] = W.predict_logit(beta, Xte)
    kn, vals = W.pav_isotonic(tr.conf.values.astype(float), ytr)
    out["isotonic_conf"] = np.clip(W.predict_pav(kn, vals, te.conf.values.astype(float)), 0.05, 0.95)
    return out


oos = W.walk_forward(df, fit_predict)
print(f"\nOUT-OF-SAMPLE: {len(oos)} rows on {oos.day.nunique()} test days (>= {W.MIN_TRAIN_DAYS} training days, horizon embargo)")
models = ["conf_as_probability", "platt_conf", "platt_score", "platt_pred", "platt_conf+score", "direction_flag_only", "isotonic_conf"]
res = W.compare_to_base(oos, models)
res_b = W.compare_to_base(oos, models, metric=W.brier, label="brier")
res["brier_gain_vs_base"] = res_b["brier_gain_vs_base"].values
res["brier_ci_lo"] = res_b["ci_lo"].values
res["brier_ci_hi"] = res_b["ci_hi"].values
pd.set_option("display.width", 200)
print(res.round(4).to_string(index=False))
print("(gain > 0 = beats the constant training base rate; CI is a day-cluster bootstrap over test days)")

# Reliability of confidence read as probability, whole sample (descriptive)
bins = pd.cut(df.conf, [0, 0.45, 0.50, 0.55, 0.60, 1.0])
rel = df.groupby(bins, observed=True).agg(n=("y", "size"), up_rate=("y", "mean"), mean_conf=("conf", "mean"))
print("\nReliability (up-rate by confidence bin; if confidence were P(up) up_rate would equal mean_conf):")
print(rel.round(3).to_string())

# Gate sweep: out of the sample that exists, does a higher gate select a higher up-rate?
print("\nGate sweep on published rows (up-rate of rows >= gate), day-cluster CI:")
pub = df[df.pub == 1]
for g in (0.40, 0.45, 0.50, 0.55, 0.60):
    s = pub[pub.conf >= g]
    if len(s) < 10:
        print(f"  gate {g:.2f}: n={len(s)} (too few)")
        continue
    est, lo, hi = W.day_boot(s[["day", "y"]], lambda x: x.y.mean())
    print(f"  gate {g:.2f}: n={len(s):3d} up-rate={est:.3f}  95% CI [{lo:.3f}, {hi:.3f}]")

# Rank correlation of the inputs with the raw return (information coefficient), day-cluster CI
print("\nInformation coefficient (Spearman with raw 1h return), pooled council rows:")
for col in ("conf", "score", "pred"):
    def ic(x, c=col):
        return x[c].rank().corr(x["act"].rank())
    est, lo, hi = W.day_boot(df[["day", col, "act"]], ic)
    print(f"  IC({col}, return) = {est:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
pubonly = df[df.pub == 1]
for col in ("conf", "score", "pred"):
    def ic(x, c=col):
        return x[c].rank().corr(x["act"].rank())
    est, lo, hi = W.day_boot(pubonly[["day", col, "act"]], ic)
    print(f"  published only IC({col}, return) = {est:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")

# Circularity: what the live _resolver_hit_rate() sees vs council-published only (all populations enter live)
raw = L.load_raw()
g = [r for r in raw if r.get("correct") is not None]
allh = np.mean([r["correct"] is True for r in g])
pubh = np.mean([r["correct"] is True for r in g if r.get("evidence_population") == "council_published"])


def conf_mult(h):
    prior = 0.7 * 0.58 + 0.3 * max(0.40, min(0.65, h))
    return prior * (0.88 + 0.24 * h)


print(f"\n_resolver_hit_rate() as the code computes it (every row with correct!=None, incl. pump + shadow + phantom-VWAP): {allh:.3f} on n={len(g)}")
print(f"  council_published only: {pubh:.3f};  confidence multiplier {conf_mult(allh):.4f} vs {conf_mult(pubh):.4f} "
      f"=> every confidence is {100*(1-conf_mult(allh)/conf_mult(pubh)):.1f}% lower because pump-desk outcomes feed council confidence")
