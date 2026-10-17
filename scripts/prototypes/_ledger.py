"""Shared clean-ledger loader for the learning-loop prototypes (stdlib + pandas/numpy, no network).

Clean filter (same as docs/learning-loop/ROOT-CAUSE-REPORT-2026-10-17.md):
outcome in (hit, miss), actual_pct present, |actual_pct| <= 50,
created_at NOT in 2026-08-07..2026-08-18 (phantom VWAP window).
Usage: LEDGER=/path/predictions_resolved.json python scripts/prototypes/<x>.py
"""
import json
import os

import numpy as np
import pandas as pd

DEFAULT = "/tmp/claude-0/-home-user-subnet-dashboard/aecb0d84-8ab6-5eb2-82c8-98ce55e7fbd6/scratchpad/predictions_resolved.json"


def load_raw(path=None):
    path = path or os.environ.get("LEDGER", DEFAULT)
    return json.load(open(path))["resolved"]


def clean_rows(path=None):
    out = []
    for r in load_raw(path):
        if r.get("outcome") not in ("hit", "miss"):
            continue
        a = r.get("actual_pct")
        if a is None or abs(a) > 50:
            continue
        ca = str(r.get("created_at", ""))[:10]
        if "2026-08-07" <= ca <= "2026-08-18":
            continue
        out.append(r)
    return out


def load(path=None, populations=None):
    out = clean_rows(path)
    df = pd.DataFrame([{
        "id": r["id"], "netuid": r["netuid"],
        "ts": pd.to_datetime(str(r["created_at"]).replace("+00:00Z", "Z"), utc=True),
        "day": str(r["created_at"])[:10], "h": r.get("horizon_hours"), "pop": r.get("evidence_population"),
        "dir": r.get("direction"), "pred": r.get("predicted_pct"), "act": r["actual_pct"],
        "hit": 1 if r["outcome"] == "hit" else 0, "expert": r.get("expert"),
        "conf": r.get("pick_confidence"), "score": r.get("pick_score"),
        "psrc": r.get("price_source"), "raw": r,
    } for r in out])
    if populations is not None:
        df = df[df["pop"].isin(populations)]
    return df.sort_values("ts").reset_index(drop=True)


def cluster_boot(values_by_day, stat, n=2000, seed=7):
    """values_by_day: dict day -> np.array of per-row values; stat: fn(concatenated arr)->float.
    Day-cluster bootstrap 95% CI."""
    rng = np.random.default_rng(seed)
    days = list(values_by_day)
    est = stat(np.concatenate([values_by_day[d] for d in days]))
    boots = []
    for _ in range(n):
        pick = rng.integers(0, len(days), len(days))
        boots.append(stat(np.concatenate([values_by_day[days[i]] for i in pick])))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(est), float(lo), float(hi)
