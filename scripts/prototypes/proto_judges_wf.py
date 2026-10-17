"""Prototype: judges (oracle / echo / pulse) -- do they forecast anything, and does the nudge rule learn?

Out-of-sample (walk-forward, _wf.py protocol) tests on council rows with judge_scores_at_creation:
  * each judge's score as P(up) through a one-feature Platt map, vs the constant base rate
  * the live consensus (weights = what prod shows now: oracle .086 / echo .638 / pulse .276), equal weights,
    echo=0 (the approved-but-unimplemented Ditto decision 2026-10-12), a signed ridge stack of the three scores
  * replay of the live judge-nudge rule from default weights on training rows (conviction scaled, symmetric steps)
  * the graded-against-council identity: for endorsing judges the judge grade equals the council grade by construction
Target y = 1 if 1h return > 0 (direction-free; shadow rows are mostly direction=down counterfactuals).
Run:  /usr/bin/python3 scripts/prototypes/proto_judges_wf.py
"""
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _wf as W

JUDGES = ["oracle", "echo", "pulse"]
THRESH = {"oracle": 0.55, "echo": 0.5, "pulse": 0.55}   # internal/judges/grading.py JUDGE_THRESHOLDS
LIVE_W = {"oracle": 0.08595, "echo": 0.63766, "pulse": 0.27639}  # /api/learning/stats 2026-10-17 (normalised below)
DEFAULT_W = {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}

df = L.load(populations=["council_published", "council_shadow"])
df = df[df.h == 1].copy()
for j in JUDGES:
    df["s_" + j] = df.raw.apply(lambda r, j=j: ((r.get("judge_scores_at_creation") or {}).get(j) or {}).get("score"))
df = df.dropna(subset=["s_" + j for j in JUDGES]).reset_index(drop=True)
df["y"] = (df.act > 0).astype(int)
df["pub"] = (df["pop"] == "council_published").astype(int)
print(f"rows={len(df)} days={df.day.nunique()} published={df.pub.sum()}")

print("\nEndorsement and score dispersion")
for j in JUDGES:
    s = df["s_" + j]
    print(f"  {j:7s} endorse-rate={np.mean(s >= THRESH[j]):.3f} mean={s.mean():.3f} sd={s.std():.3f} min={s.min():.3f} max={s.max():.3f}")
print("  score correlations:\n" + df[["s_" + j for j in JUDGES]].corr().round(2).to_string())

print("\nJudge grade vs council grade (published rows): fraction of rows where judge_nudge_correct == council hit")
pub = df[df.pub == 1]
for j in JUDGES:
    endorsed = pub["s_" + j] >= THRESH[j]
    judge_correct = np.where(endorsed, pub.y == 1, pub.y == 0)  # council hit == up for published longs
    print(f"  {j:7s} identical-to-council on {np.mean(judge_correct == (pub.y == 1)):.3f} of rows (1.0 = judge grade carries no information beyond the council grade)")

print("\nDirect discrimination: AUC of judge score for P(up), whole sample, day-cluster CI (0.5 = none)")
for j in JUDGES:
    est, lo, hi = W.day_boot(df[["day", "y", "s_" + j]], lambda x, j=j: W.auc(x.y.values, x["s_" + j].values))
    print(f"  {j:7s} AUC={est:.3f} [{lo:.3f},{hi:.3f}]")
    pe, plo, phi = W.day_boot(pub[["day", "y", "s_" + j]], lambda x, j=j: W.auc(x.y.values, x["s_" + j].values))
    print(f"           published only: AUC={pe:.3f} [{plo:.3f},{phi:.3f}]")


def norm(w):
    t = sum(w.values())
    return {k: v / t for k, v in w.items()}


def cons(X, w):
    w = norm(w)
    return sum(X[:, i] * w[j] for i, j in enumerate(JUDGES))


def replay(train, start):
    """live judge rule: symmetric +-0.02 * scale, scale = move_scale * conviction (floor .25), published rows only."""
    w = dict(start)
    for _, r in train.sort_values("ts").iterrows():
        if r.pub != 1:
            continue
        for j in JUDGES:
            sc = r["s_" + j]
            endorsed = sc >= THRESH[j]
            hit = bool(r.y)
            correct = hit if endorsed else (not hit)
            ratio = min(3.0, abs(r.act) / max(abs(r.pred or 0), 0.5))
            if ratio > 1.0:
                ratio = 1.0 + math.log(ratio)
            if not correct:
                ratio = max(1.0, ratio)
            ratio *= max(0.25, min(1.0, abs(sc - THRESH[j]) * 2.0))
            w[j] = float(np.clip(w[j] + (0.02 if correct else -0.02) * ratio, 0.1, 2.0))
    return w


def platt(c_tr, y_tr, c_te):
    mu, sd = c_tr.mean(), c_tr.std() + 1e-9
    beta = W.fit_logit(((c_tr - mu) / sd)[:, None], y_tr.astype(float), l2=5.0)
    return W.predict_logit(beta, ((c_te - mu) / sd)[:, None])


def fit_predict(tr, te):
    Xtr = tr[["s_" + j for j in JUDGES]].values.astype(float)
    Xte = te[["s_" + j for j in JUDGES]].values.astype(float)
    ytr = tr.y.values.astype(float)
    out = {"base": np.full(len(te), np.clip(ytr.mean(), 0.05, 0.95))}
    for i, j in enumerate(JUDGES):
        out["judge_" + j] = platt(Xtr[:, i], ytr, Xte[:, i])
    out["consensus_live_weights"] = platt(cons(Xtr, LIVE_W), ytr, cons(Xte, LIVE_W))
    out["consensus_equal"] = platt(cons(Xtr, {j: 1.0 for j in JUDGES}), ytr, cons(Xte, {j: 1.0 for j in JUDGES}))
    w0 = {"oracle": 1.0, "echo": 0.0, "pulse": 1.0}
    out["consensus_echo_zero"] = platt(cons(Xtr, w0), ytr, cons(Xte, w0))
    wr = replay(tr, DEFAULT_W)
    out["consensus_nudge_replay"] = platt(cons(Xtr, wr), ytr, cons(Xte, wr))
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    beta = W.fit_logit((Xtr - mu) / sd, ytr, l2=20.0)
    out["ridge_stack_signed"] = W.predict_logit(beta, (Xte - mu) / sd)
    return out


oos = W.walk_forward(df, fit_predict)
print(f"\nOUT-OF-SAMPLE: {len(oos)} rows, {oos.day.nunique()} test days")
models = ["judge_oracle", "judge_echo", "judge_pulse", "consensus_live_weights", "consensus_equal", "consensus_echo_zero", "consensus_nudge_replay", "ridge_stack_signed"]
res = W.compare_to_base(oos, models)
pd.set_option("display.width", 200)
print(res.round(4).to_string(index=False))
print("(logloss gain > 0 beats the constant base rate; day-cluster CI)")

# Brier skill vs base (the FX4 acceptance metric)
print("\nBrier skill score vs base rate, out of sample (positive = better):")
for m in models:
    bs, bb = W.brier(oos.y.values, oos[m].values).mean(), W.brier(oos.y.values, oos["base"].values).mean()
    print(f"  {m:24s} BSS={1-bs/bb:+.4f}")

# What the live nudge rule converges to on the full clean ledger (for comparison with prod 0.086/0.638/0.276)
w_end = replay(df, DEFAULT_W)
print("\nLive judge-nudge rule replayed on the whole clean published ledger from defaults:", {k: round(v, 3) for k, v in norm(w_end).items()},
      "(prod today: oracle .086 / echo .638 / pulse .276 -- not reproducible, see F28)")
