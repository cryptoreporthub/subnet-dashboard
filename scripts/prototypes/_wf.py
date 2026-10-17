"""Walk-forward helpers shared by the learning-loop prototypes (numpy/pandas only, no network).

Protocol (identical for every prototype so results are comparable):
  * rows sorted by creation time; an *expanding* training window of all rows from days strictly before the test day
  * a horizon embargo: training rows must have resolved before the start of the test day
  * minimum MIN_TRAIN_DAYS distinct training days before predicting anything
  * every candidate is scored against a constant baseline = the training up-rate
  * uncertainty = bootstrap over TEST DAYS (rows within a day share the market, so rows are not independent)
"""
import numpy as np
import pandas as pd

MIN_TRAIN_DAYS = 20
EPS = 1e-4


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def logloss(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier(y, p):
    return (y - p) ** 2


def fit_logit(X, y, l2=1.0, iters=50):
    """Ridge logistic regression with intercept (unpenalised). X: (n,k). Returns beta (k+1,)."""
    n, k = X.shape
    A = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = np.eye(k + 1) * l2
    pen[0, 0] = 0.0
    for _ in range(iters):
        p = sigmoid(A @ beta)
        W = p * (1 - p) + 1e-9
        g = A.T @ (y - p) - pen @ beta
        Hm = (A * W[:, None]).T @ A + pen
        step = np.linalg.solve(Hm, g)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def predict_logit(beta, X):
    A = np.hstack([np.ones((X.shape[0], 1)), X])
    return sigmoid(A @ beta)


def pav_isotonic(x, y):
    """Pool-adjacent-violators; returns (xs, fitted) step function knots (monotone non-decreasing)."""
    order = np.argsort(x, kind="mergesort")
    xs, ys = x[order], y[order].astype(float)
    vals, wts, bounds = [], [], []
    for xi, yi in zip(xs, ys):
        vals.append(yi); wts.append(1.0); bounds.append(xi)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            w = wts[-2] + wts[-1]
            vals.pop(); wts.pop(); bounds.pop()
            vals[-1], wts[-1] = v, w
    return np.array(bounds), np.array(vals)


def predict_pav(knots, vals, x):
    idx = np.searchsorted(knots, x, side="right") - 1
    idx = np.clip(idx, 0, len(vals) - 1)
    return vals[idx]


def auc(y, s):
    y = np.asarray(y); s = np.asarray(s)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    r = pd.Series(np.concatenate([pos, neg])).rank().values
    return (r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def day_boot(df, stat, n=2000, seed=11, daycol="day"):
    """Bootstrap over days. df must hold the columns `stat` needs. Returns (estimate, lo, hi)."""
    rng = np.random.default_rng(seed)
    groups = {d: g for d, g in df.groupby(daycol)}
    days = list(groups)
    est = stat(df)
    if len(days) < 3:
        return est, np.nan, np.nan
    vals = []
    for _ in range(n):
        pick = rng.integers(0, len(days), len(days))
        vals.append(stat(pd.concat([groups[days[i]] for i in pick])))
    vals = np.array(vals, dtype=float)
    vals = vals[~np.isnan(vals)]
    return est, float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def walk_forward(df, fit_predict, min_train_days=MIN_TRAIN_DAYS, horizon_col="h", embargo=True):
    """df: rows with columns day, ts, y (+ whatever fit_predict needs).
    fit_predict(train_df, test_df) -> dict name -> prob array for test rows (must include 'base').
    Returns long DataFrame of out-of-sample predictions: test rows plus one column per model."""
    days = sorted(df.day.unique())
    out = []
    for i, d in enumerate(days):
        train = df[df.day < d]
        if embargo and horizon_col in df.columns:
            cutoff = pd.Timestamp(d, tz="UTC")
            train = train[train.ts + pd.to_timedelta(train[horizon_col], unit="h") <= cutoff]
        if train.day.nunique() < min_train_days or len(train) < 30:
            continue
        test = df[df.day == d]
        preds = fit_predict(train, test)
        res = test.copy()
        for k, v in preds.items():
            res[k] = np.asarray(v, dtype=float)
        out.append(res)
    return pd.concat(out) if out else pd.DataFrame()


def compare_to_base(oos, models, base="base", metric=logloss, label="logloss"):
    """For each model: mean(metric_base - metric_model) per row (positive = model better) with day-cluster CI."""
    rows = []
    for m in models:
        d = oos[["day"]].copy()
        d["delta"] = metric(oos.y.values, oos[base].values) - metric(oos.y.values, oos[m].values)
        est, lo, hi = day_boot(d, lambda x: x.delta.mean())
        rows.append({"model": m, f"{label}_gain_vs_base": est, "ci_lo": lo, "ci_hi": hi,
                     "auc": auc(oos.y.values, oos[m].values), "n_oos": len(oos), "test_days": oos.day.nunique()})
    return pd.DataFrame(rows)
