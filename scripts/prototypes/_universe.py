"""Universe panel from the committed data/price_cache.json (7 days x ~129 subnets of hourly TMC candles,
Jul 31 - Aug 14 2026). The only whole-universe price history in the repo; no network.

Limits (stated in ARCHITECT-VERDICTS.md): ~7 usable days, USD-scale candles (Ditto 2026-10-12: TMC candles
rescale historical TAO/USD, so absolute levels are untrusted; cross-sectional *excess* returns are robust to a
common factor), different subnets end at different fetch times, so use the overlap window only.
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "..", "data", "price_cache.json")


def load_panel(path=None, min_names=60):
    path = path or os.environ.get("PRICE_CACHE", DEFAULT)
    raw = json.load(open(path))
    close, vol, high, low = {}, {}, {}, {}
    for k, v in raw.items():
        if not isinstance(v, dict) or not v.get("candles"):
            continue
        ts = [pd.Timestamp(c["timestamp"]) for c in v["candles"]]
        close[k] = pd.Series([c.get("close") for c in v["candles"]], index=ts, dtype=float)
        vol[k] = pd.Series([c.get("volume") or 0.0 for c in v["candles"]], index=ts, dtype=float)
        high[k] = pd.Series([c.get("high") for c in v["candles"]], index=ts, dtype=float)
        low[k] = pd.Series([c.get("low") for c in v["candles"]], index=ts, dtype=float)
    C = pd.DataFrame(close).sort_index()
    V = pd.DataFrame(vol).sort_index()
    H = pd.DataFrame(high).sort_index()
    Lw = pd.DataFrame(low).sort_index()
    # keep hours where enough names are observed
    ok = C.notna().sum(axis=1) >= min_names
    return C[ok], V[ok], H[ok], Lw[ok]


def forward_returns(C, k=1):
    """pct return from close_t to close_{t+k} (what a pick made at hour t earns)."""
    return (C.shift(-k) / C - 1.0) * 100.0
