"""Prototype: weight estimator for signals/experts, walk-forward on the clean ledger.

Compares, out of sample, the *estimators* that could turn graded outcomes into signal weights:
  live_stored      composite using the weights the system actually had at creation (weights_at_creation / signal weight)
  online_asym      replay of the live nudge rule (+0.02 hit / -0.03 miss, clamp 0.1-2.0, active signals only,
                   shadow rows skipped exactly as resolver._skip_council_learning does) on training rows only
  online_sym       same with symmetric +-0.02 (the fix the judges module already adopted, commit 15292648)
  equal            unweighted mean of the 8 signal scores
  ridge_logit      batch ridge logistic regression on the 8 scores (signed, so it CAN invert an anti-predictive signal)
  shrunk_ic        batch: per-signal Spearman IC shrunk toward 0 with n/(n+k) (signed)
Every composite goes through the same one-feature Platt calibration fitted on training rows, then is scored against
the constant training base rate (walk_forward protocol in _wf.py). Target y = 1 if 1h return > 0.

Also: (A) persistence test that is the falsifier for online expert nudging, (B) which signals carry any variance.
Run:  /usr/bin/python3 scripts/prototypes/proto_weights_wf.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _wf as W

SIGS = ["rsi_crossover", "macd_cross", "stochastic_reversal", "bollinger_squeeze", "mfi_flow", "cci_divergence", "williams_r", "keltner_channel"]
STEP_HIT, STEP_MISS = 0.02, -0.03

df = L.load(populations=["council_published", "council_shadow"])
df = df[df.h == 1].copy()
for s in SIGS:
    df[s] = df.raw.apply(lambda r, s=s: (r.get("signal_contributions") or {}).get(s, {}).get("score"))
    df["w_" + s] = df.raw.apply(lambda r, s=s: (r.get("signal_contributions") or {}).get(s, {}).get("weight"))
df["active"] = df.raw.apply(lambda r: set(r.get("active_signals") or []))
df["y"] = (df.act > 0).astype(int)
df["pub"] = (df["pop"] == "council_published").astype(int)
df = df.dropna(subset=SIGS).reset_index(drop=True)
print(f"rows={len(df)} days={df.day.nunique()}  published={df.pub.sum()}")

# (B) variance carried by each signal
print("\nSignal information content (share of rows equal to the modal value; |IC| with return; day-cluster CI)")
for s in SIGS:
    modal = df[s].round(3).value_counts(normalize=True).iloc[0]
    est, lo, hi = W.day_boot(df[["day", s, "act"]], lambda x, s=s: x[s].rank().corr(x["act"].rank()))
    print(f"  {s:20s} modal-share={modal:.2f}  IC={est:+.3f} [{lo:+.3f},{hi:+.3f}]  stored weight range {df['w_'+s].min():.2f}-{df['w_'+s].max():.2f}")
print("  note: positive-only weights in [0.1, 2.0] cannot express a negative IC; the best the live rule can do for an anti-predictive signal is sit at 0.1.")


def replay(train, hit_step, miss_step):
    w = {s: 1.0 for s in SIGS}
    for _, r in train.sort_values("ts").iterrows():
        if r.pub != 1:  # live nudge skips council_shadow rows
            continue
        correct = bool(r.y)  # published rows are direction=up so hit == up
        for s in r.active & set(SIGS):
            w[s] = float(np.clip(w[s] + (hit_step if correct else miss_step), 0.1, 2.0))
    return np.array([w[s] for s in SIGS])


def composite(Wv, X):
    Wv = np.asarray(Wv, float)
    return (X * Wv).sum(axis=1) / Wv.sum()


def platt_prob(c_tr, y_tr, c_te):
    mu, sd = c_tr.mean(), c_tr.std() + 1e-9
    beta = W.fit_logit(((c_tr - mu) / sd)[:, None], y_tr.astype(float), l2=5.0)
    return W.predict_logit(beta, ((c_te - mu) / sd)[:, None])


def fit_predict(tr, te):
    Xtr, Xte = tr[SIGS].values.astype(float), te[SIGS].values.astype(float)
    ytr = tr.y.values.astype(float)
    out = {"base": np.full(len(te), np.clip(ytr.mean(), 0.05, 0.95))}
    # stored weights at creation (what the live system believed)
    stored_tr = np.array([composite(r[["w_" + s for s in SIGS]].values.astype(float), r[SIGS].values.astype(float)[None, :])[0] for _, r in tr.iterrows()])
    stored_te = np.array([composite(r[["w_" + s for s in SIGS]].values.astype(float), r[SIGS].values.astype(float)[None, :])[0] for _, r in te.iterrows()])
    out["live_stored"] = platt_prob(stored_tr, ytr, stored_te)
    out["equal"] = platt_prob(Xtr.mean(axis=1), ytr, Xte.mean(axis=1))
    wa = replay(tr, STEP_HIT, STEP_MISS)
    out["online_asym"] = platt_prob(composite(wa, Xtr), ytr, composite(wa, Xte))
    ws = replay(tr, 0.02, -0.02)
    out["online_sym"] = platt_prob(composite(ws, Xtr), ytr, composite(ws, Xte))
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    beta = W.fit_logit((Xtr - mu) / sd, ytr, l2=20.0)
    out["ridge_logit"] = W.predict_logit(beta, (Xte - mu) / sd)
    ics = np.array([pd.Series(Xtr[:, j]).rank().corr(pd.Series(tr.act.values).rank()) for j in range(len(SIGS))])
    ics = np.nan_to_num(ics)
    k = 200.0
    shr = ics * len(tr) / (len(tr) + k)
    z = (Xtr - mu) / sd
    out["shrunk_ic"] = platt_prob(z @ shr, ytr, ((Xte - mu) / sd) @ shr)
    return out


oos = W.walk_forward(df, fit_predict)
print(f"\nOUT-OF-SAMPLE signal-weight estimators: {len(oos)} rows, {oos.day.nunique()} test days")
res = W.compare_to_base(oos, ["live_stored", "online_asym", "online_sym", "equal", "ridge_logit", "shrunk_ic"])
pd.set_option("display.width", 200)
print(res.round(4).to_string(index=False))
print("(logloss gain > 0 beats the constant base rate; CI = day-cluster bootstrap over test days)")


# Direction of the composites (in-sample, descriptive): Platt can flip a sign, so state what the raw composite does
Xall = df[SIGS].values.astype(float)
stored_all = np.array([composite(r[["w_" + s for s in SIGS]].values.astype(float), r[SIGS].values.astype(float)[None, :])[0] for _, r in df.iterrows()])
tmp = df[["day", "act"]].copy()
tmp["stored"], tmp["equal"] = stored_all, Xall.mean(axis=1)
for c in ("stored", "equal"):
    est, lo, hi = W.day_boot(tmp, lambda x, c=c: x[c].rank().corr(x["act"].rank()))
    print(f"IC(raw composite '{c}' weights, 1h return) = {est:+.3f} [{lo:+.3f},{hi:+.3f}]   (negative = higher council technical score -> LOWER next-hour return)")
mu, sd = Xall.mean(0), Xall.std(0) + 1e-9
bfull = W.fit_logit((Xall - mu) / sd, df.y.values.astype(float), l2=20.0)
print("full-sample ridge coefficients (standardised, in-sample, descriptive):", {s_: round(float(b), 3) for s_, b in zip(SIGS, bfull[1:])})

# (A) persistence: is an expert's recent hit rate informative beyond the overall recent hit rate?
pub = df[df.pub == 1].sort_values("ts").reset_index(drop=True)
N = 20
rows = []
for i in range(N, len(pub)):
    past = pub.iloc[max(0, i - 60):i]
    r = pub.iloc[i]
    pe = past[past.expert == r.expert].y.tail(N)
    pa = past.y.tail(N)
    if len(pe) >= 8:
        rows.append({"day": r.day, "y": r.y, "trail_expert": pe.mean(), "trail_all": pa.mean(), "w_expert_at_creation": r.raw["weights_at_creation"].get(r.expert, np.nan)})
P = pd.DataFrame(rows)
print(f"\nPersistence (published rows, n={len(P)}): does the attributed expert's trailing hit rate predict the next hit?")
for col in ("trail_expert", "trail_all", "w_expert_at_creation"):
    est, lo, hi = W.day_boot(P, lambda x, c=col: x[c].corr(x["y"]))
    print(f"  corr({col}, next hit) = {est:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
resid = P.copy()
resid["trail_expert_resid"] = resid.trail_expert - resid.trail_all
est, lo, hi = W.day_boot(resid, lambda x: x.trail_expert_resid.corr(x["y"]))
print(f"  corr(expert trailing minus overall trailing, next hit) = {est:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  <- expert-specific skill signal")

# Weight at creation vs outcome by expert (F17 analogue for experts)
print("\nStored expert weight at creation vs hit, by attributed expert (published):")
for e in ("hype", "technical"):
    g = pub[pub.expert == e]
    g = g.assign(w=g.raw.apply(lambda r, e=e: r["weights_at_creation"].get(e)))
    est, lo, hi = W.day_boot(g[["day", "w", "y"]], lambda x: x["w"].corr(x["y"]))
    print(f"  {e:10s} n={len(g):3d} corr(weight, hit) = {est:+.3f}  [{lo:+.3f},{hi:+.3f}]  weight range {g.w.min():.2f}-{g.w.max():.2f}")

# What the live rule converges to under a hit rate below break-even (illustrates drift without skill)
rng = np.random.default_rng(0)
for p in (0.44, 0.477, 0.55, 0.60, 0.65):
    ws = []
    for _ in range(300):
        w = 1.0
        for _ in range(250):
            w = float(np.clip(w + (0.02 if rng.random() < p else -0.03), 0.1, 2.0))
        ws.append(w)
    print(f"  asymmetric rule, true hit {p:.3f}: weight after 250 resolves, median {np.median(ws):.2f} (symmetric rule would drift {250*(2*p-1)*0.02:+.1f} before clamp)")


# ---- sensitivity of the one estimator that beat the constant: signed ridge. Different penalties, and published rows only
# (published = signal-bullish longs; pooling with the bearish shadow rows could let a population flag masquerade as signal skill)
def ridge_fp(l2):
    def f(tr, te):
        Xtr, Xte = tr[SIGS].values.astype(float), te[SIGS].values.astype(float)
        ytr = tr.y.values.astype(float)
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        beta = W.fit_logit((Xtr - mu) / sd, ytr, l2=l2)
        return {"base": np.full(len(te), np.clip(ytr.mean(), 0.05, 0.95)), f"ridge_l2={l2}": W.predict_logit(beta, (Xte - mu) / sd)}
    return f


print("\nSensitivity of signed ridge (logloss gain vs constant, day-cluster CI):")
for label, d in (("pooled published+shadow", df), ("published only", df[df.pub == 1].reset_index(drop=True))):
    for l2 in (5.0, 20.0, 100.0):
        o = W.walk_forward(d, ridge_fp(l2))
        r = W.compare_to_base(o, [f"ridge_l2={l2}"]).iloc[0]
        print(f"  {label:24s} l2={l2:6.1f}  gain {r.logloss_gain_vs_base:+.4f} [{r.ci_lo:+.4f},{r.ci_hi:+.4f}]  AUC {r.auc:.3f}  n_oos={int(r.n_oos)}")
print("  6 estimators + 3 penalties x 2 populations were examined: a lone CI lower bound near zero is NOT evidence of an edge (multiplicity).")
