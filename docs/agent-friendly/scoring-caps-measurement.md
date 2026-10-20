---
cursor:
  subagentId: "bc-2b73b904-2901-50eb-9140-0a0daddb3cc1"
---

# Scoring caps — measurement log

**Investigation window:** 2026-10-17 ~21:46–21:53 UTC  
**Code pin:** `ef234c95aa227c21318dd7292ad8228003495589`  
**Methods:** explain-the-number (derive every total from per-unit × count), attack-the-premise (registry-only local bench is not prod).

## Production (read-only, Fly app `subnet-dashboard`)

Commands:

```bash
export PATH="$HOME/.fly/bin:$PATH"
flyctl status -a subnet-dashboard
curl -sS https://subnet-dashboard.fly.dev/health
curl -sS https://subnet-dashboard.fly.dev/metrics | rg 'subnet_score_snapshot|chain_rpc|process_resident'
```

| Metric | Value | Explanation |
|--------|-------|-------------|
| `subnet_score_snapshot_build_wall_seconds` | **57.70 s** | Wall time of last background snapshot **build** (scoring loop), not HTTP handler |
| `subnet_score_snapshot_horizon_succeeded{day}` | **40** | Day horizon scored count = `SCORE_SNAPSHOT_MAX_SUBNETS` Fly default |
| `subnet_score_snapshot_horizon_copied{hour}` | **40** | Hour scores copied from day (no independent hour pass) |
| `subnet_score_snapshot_coverage_complete` | **0.0** | Last cycle not “complete” vs full membership |
| `subnet_score_snapshot_age_seconds` | **~608 s** | On-disk snapshot freshness |
| **Per-name day cost (prod)** | **57.70 ÷ 40 ≈ 1.44 s/name** | Single division; aligns with Ditto evening note **53.06 s / 40 ≈ 1.33 s** (different scrape time) |
| `process_resident_memory_bytes` | **~413 MB** | ~40% of 1 GB VM at scrape time |
| `chain_rpc_requests_total{…outcome="rate_limited"}` | **44** (counter) | Blockmachine `chain_getBlockHash` 429s since process start — not zero, but minority vs 251 ok |
| Machine | `shared-cpu-2x:1024MB` | Single `web` machine `7841024b3712e8` |

### Claude ~170 s claim — validated (extrapolation, not a single prod trace)

**Premise attacked:** “Removing caps” means scoring **full tradable membership** on the **same synchronous path** as today’s capped handlers (hour+day pair per name).

**Arithmetic:**

- Measured prod: **~1.44 s per day-scored name** (57.7 s / 40).
- Ditto / prior prod note: **~127 names with price+volume** (tradable core); **~165** broader tradable — use **127** as conservative core.
- If request path ran **hour+day** like `score_universe`: multiply by **2** horizons → **~2.88 s/name**.
- **127 × 2.88 s ≈ 366 s** (upper bound if hour were independently scored).
- With **hour copied from day** (prod snapshot path): **127 × 1.44 s ≈ 183 s** ≈ **170 s** (within ~8% of Claude’s figure).

**Falsifier attempted:** Local `REGISTRY_ONLY` bench scored 129 subnets in **0.12 s** — **not prod representative** (no pump ladder, calibration rebuild, or live OHLCV). Reject as evidence against 170 s.

**Verdict:** **~170 s is plausible and numerically supported** for uncapped **request-path** day scoring at observed prod per-name cost; not re-measured end-to-end on prod (would require lifting caps or SSH scoring — out of scope).

## Local / sandbox

### Registry-only scoring (anti-pattern for prod claims)

```bash
cd /workspace && source .venv/bin/activate
REGISTRY_ONLY=on python3 -c "..."  # see worker notes 2026-10-17
```

| Case | N | Wall (score_universe) | Per subnet (pair) |
|------|---|----------------------|-------------------|
| Capped (TOP=20) | 20 | 0.02 s | ~0.001 s |
| Full hydrate | 128 | 0.12 s | ~0.001 s |

Per-subnet median `score_subnet_for_day` **0.71 ms** — fixture-thin.

### Prototype branch (snapshot read path)

After `build_top_picks_from_snapshot`: **~1.54 ms** per `_build_top_picks()` call (50-iteration average with fixture snapshot).

### Per-name calibration bug (Ditto `ec3c24cc`) — **confirmed mechanism, not on prod**

**Prod (`ef234c95`):** hoist **absent** on snapshot path. **Local:** TELEGRAM=on, 50 ms mocked `_conviction_rows` → **2.06 s / 40** without hoist vs **0.01 s** with hoist (`scoring-caps-profile.md`). Ditto **805 ms**/read ⇒ **~32 s / 40** explains majority of **57.7 s** build.

### Draft branch harness (2026-10-17, `cursor/scoring-profile-2b73`)

128 tradable, hoist on, pump fixture: **0.068 s** serial / **0.061 s** parallel (4 workers), RSS **85.7 MB** — thin sandbox only. See `docs/scoring-caps-profile.md`.

## RPC / Finney + Blockmachine

Prod metrics show Blockmachine endpoint with **rate_limited** outcomes present but **not dominating** ok counts at scrape time. **Cannot conclude** caps are obsolete from RPC alone — snapshot build still **~58 s for 40 names** and RSS **~413 MB**.
