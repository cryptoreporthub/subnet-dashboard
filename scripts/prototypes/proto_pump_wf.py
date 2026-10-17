"""Prototype: pump-desk claim logic -- is a point claim "+2% in 1h" a calibrated forecast, and does the lead score rank?

Facts computed from the clean ledger (live grading rule: hit iff actual_pct >= predicted_pct, default 2.0):
  * base rate of a >= +2% 1h move for names the council publishes vs names the pump desk claims
  * out-of-sample (walk-forward, _wf.py protocol; min 20 training days) discrimination of the desk's own score
    (composite_score, combined_pts, phase) for label (a) >= +2% and (b) any up move
  * how many positives exist vs what a feature model would need (events-per-variable rule of thumb)
  * the alternative claim format: publish a calibrated probability P(>= +2% in 1h) (shrunk to the base rate) graded by Brier

Run: /usr/bin/python3 scripts/prototypes/proto_pump_wf.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ledger as L
import _wf as W

df = L.load()
p = df[df["pop"].str.startswith("pump")].copy().reset_index(drop=True)
c = df[df["pop"].isin(["council_published", "council_shadow"]) & (df.h == 1)]
p["ge2"] = (p.act >= p.pred.fillna(2.0)).astype(int)   # the live rule
p["up"] = (p.act > 0).astype(int)
p["cs"] = p.raw.apply(lambda r: r.get("composite_score")).astype(float)
p["combined"] = p.raw.apply(lambda r: r.get("combined_pts")).astype(float)
p["phase"] = p.raw.apply(lambda r: r.get("pump_phase"))
for ph in ("STIRRING", "ACCUMULATING", "PUMPING"):
    p["ph_" + ph] = (p.phase == ph).astype(int)

print("Base rates of a >= +2% 1h move (day-cluster CI):")
for nm, g in (("council_published", c[c["pop"] == "council_published"]), ("council_shadow", c[c["pop"] == "council_shadow"]),
              ("pump_combined_experimental", p[p["pop"] == "pump_combined_experimental"]), ("pump_early", p[p["pop"] == "pump_early"]),
              ("pump_just_started", p[p["pop"] == "pump_just_started"])):
    g = g.assign(ge2=(g.act >= 2).astype(int))
    e, lo, hi = W.day_boot(g[["day", "ge2"]], lambda x: x.ge2.mean())
    print(f"  {nm:28s} n={len(g):4d} P(>=+2%)={e:.3f} [{lo:.3f},{hi:.3f}]  sd of 1h return={g.act.std():.2f}%")
print("  => a desk claim of +2% in 1h is realised less often than a random council-liked name moves +2%; the claim is not volatility-aware.")

pos = int(p.ge2.sum())
print(f"\nPositives for label >=+2%: {pos} of {len(p)} pump rows; rows with a frozen feature_vector: {int(p.raw.apply(lambda r: bool(r.get('feature_vector'))).sum())} "
      f"(positives among them: {int(p[p.raw.apply(lambda r: bool(r.get('feature_vector')))].ge2.sum())}).")
print(f"  events-per-variable rule (>=10 positives per feature): supports at most {pos//10} free parameters on all rows, "
      f"{int(p[p.raw.apply(lambda r: bool(r.get('feature_vector')))].ge2.sum())//10} on the 11-feature vector set -> an XGBoost/feature model (pump_lead_train.py) is not estimable.")


def fp(label):
    def f(tr, te):
        ytr = tr[label].values.astype(float)
        out = {"base": np.full(len(te), np.clip(ytr.mean(), 0.01, 0.99))}
        for nm, cols in {"composite_score": ["cs"], "phase_dummies": ["ph_STIRRING", "ph_ACCUMULATING", "ph_PUMPING"],
                         "score+phase": ["cs", "ph_STIRRING", "ph_ACCUMULATING", "ph_PUMPING"]}.items():
            Xtr, Xte = tr[cols].values.astype(float), te[cols].values.astype(float)
            mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
            beta = W.fit_logit((Xtr - mu) / sd, ytr, l2=10.0)
            out[nm] = np.clip(W.predict_logit(beta, (Xte - mu) / sd), 0.005, 0.995)
        out["claim_as_probability(=1.0)"] = np.full(len(te), 0.995)
        return out
    return f


pd.set_option("display.width", 200)
for label, nm in (("ge2", "label: act >= +2% (the desk's claim)"), ("up", "label: act > 0")):
    d = p.rename(columns={label: "y"}).reset_index(drop=True)
    oos = W.walk_forward(d, fp("y") if False else (lambda tr, te: fp("y")(tr, te)))
    print(f"\nOUT-OF-SAMPLE {nm}: {len(oos)} rows, {oos.day.nunique()} test days, base-rate {oos.y.mean():.3f}")
    res = W.compare_to_base(oos, ["composite_score", "phase_dummies", "score+phase", "claim_as_probability(=1.0)"])
    print(res.round(4).to_string(index=False))
    if label == "ge2":
        # lift in the top tertile of the desk score, out of sample (score fixed by the desk; no fitting)
        q = oos.cs.quantile([1 / 3, 2 / 3]).values
        top = oos[oos.cs >= q[1]]; bot = oos[oos.cs <= q[0]]
        e, lo, hi = W.day_boot(oos.assign(top=(oos.cs >= q[1]).astype(int), bot=(oos.cs <= q[0]).astype(int))[["day", "y", "top", "bot"]],
                                lambda x: x[x.top == 1].y.mean() - x[x.bot == 1].y.mean())
        print(f"  top-tertile minus bottom-tertile hit rate on the desk composite_score: {e:+.3f} [{lo:+.3f},{hi:+.3f}] (top n={len(top)} {top.y.mean():.3f}; bottom n={len(bot)} {bot.y.mean():.3f})")

# Reliability of the claim as written: every claim implies "this will move >= +2%"
print(f"\nClaim-as-written realised rate: {p.ge2.mean():.3f} (n={len(p)}). Brier of always-claim (p=1): {np.mean((1-p.ge2)**2):.3f}; Brier of the base rate: {np.mean((p.ge2-p.ge2.mean())**2):.3f}")


# ---- the live pump learner: internal/learning/pump_calibration._online_update_blend_weights (applied on EVERY pump resolve, no n gate)
print("\nLive online blend-weight update replayed over the clean pump rows that carry a signal_snapshot (chronological, from defaults):")
w = {"volume": 0.30, "momentum": 0.25, "price": 0.20, "flow": 0.10, "chatter": 0.10}
w0 = dict(w)
n_upd = 0
for _, r in p.sort_values("ts").iterrows():
    snap = r.raw.get("signal_snapshot")
    if not isinstance(snap, dict):
        continue
    correct = bool(r.ge2)  # live rule label
    feats = {"volume": float(snap.get("volume_intensity") or 0.0), "momentum": min(max(float(snap.get("momentum_1h") or 0.0) / 0.04, 0.0), 1.0),
             "price": min(max(float(snap.get("price_change_24h") or 0.0) / 0.08, 0.0), 1.0), "flow": max(float(snap.get("buy_ratio") or 0.5) - 0.5, 0.0) * 2.0,
             "chatter": float(snap.get("chatter_intensity") or 0.0)}
    for k, v in feats.items():
        w[k] = max(0.02, w[k] + 0.005 * (1.0 if correct else -1.0) * (v - 0.5))
    tot = sum(w.values())
    w = {k: round(v / tot * 0.95, 4) for k, v in w.items()}
    n_upd += 1
print(f"  updates={n_upd}  hit rate in those rows={p[p.raw.apply(lambda r: isinstance(r.get('signal_snapshot'), dict))].ge2.mean():.3f}")
print("  start:", w0)
print("  after:", w, " <- 'flow' (input is the default 0.5 buy_ratio in 97% of rows, i.e. no data) is the weight that grows on a miss")
