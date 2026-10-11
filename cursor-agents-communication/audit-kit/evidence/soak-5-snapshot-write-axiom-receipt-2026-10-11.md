# Soak 5 — score-snapshot write / stall-guard Axiom receipt

| Field | Value |
|---|---|
| Label | **MC-verified Axiom export** (Mission Control query of `subnet-dashboard-prod`; **not** Replit-independent verification) |
| Attribution | MC (Grok Bot) → filed in repo for MC/Joshua audit trail · source table copied from Project store soak receipt `2026-10-11` |
| Deploy land | `2026-10-10T12:09:46Z` |
| Deploy pin | `5d840ba4` (Deploy C) |
| Machine | `7841024b3712e8` |
| Axiom dataset | `subnet-dashboard-prod` |
| Query window (bucket coverage) | `2026-10-10T12:11:00Z` → `2026-10-11T13:15:00Z` |
| Separate MC query (resolver first-success) | Post-deploy trace **outside** window start — see below |
| Filed | `2026-10-11` (sanitized; no secrets) |

**Scope:** factual prod log lines supporting Phase 1 AC #9 **(b)** — historical Soak 5 interpretation (snapshot-write cost vs resolver). Stall-guard strict verdict remains **GUARD_FAIL** per merge-soak criteria; this receipt does not upgrade that gate.

---

## Coverage summary

| Metric | Value |
|--------|--------|
| Events in window | **13,742** |
| First event | `12:11:07Z` |
| Last event | `13:14:57Z` |
| Bucket coverage | Every **30-minute** bucket has events (no gaps) |

---

## First post-deploy resolver success (separate MC Axiom datum)

Not inside the `12:11:00Z` window above (first **in-window** event: `12:11:07Z`). Sourced from MC’s dedicated post-deploy resolver trace (same dataset/machine/deploy pin).

| UTC | Event |
|-----|--------|
| **`2026-10-10T12:10:54.888Z`** | `resolver lifecycle event=success` **`first=True`** `duration_ms=5694.3` |

Subsequent resolver successes (~15–17 min cadence): `12:27:41Z`, `12:44:16Z`, `12:59:19Z`, `13:15:03Z`. Resolver cadence healthy throughout window — not classified as root cause of stall-guard strikes.

---

## Stall-guard / snapshot-write lines (after first resolver success)

| UTC | Event |
|-----|--------|
| `2026-10-10T12:37:51Z` | `snapshot STALE` age=**14569s** **strike=1/3** |
| `2026-10-10T12:46:23Z` | in-place **revive** failed (`revived=False`); `already running`; **`write_timeout_480s`** |
| `2026-10-10T12:50:27Z` | `snapshot STALE` age=**15322s** **strike=2/3** |

After `12:50:27Z`: no strike=3, no kill, no OOM / exit **137**; stall-guard silent ~22.4h through window end.

**Interpretation (MC):** score snapshot carryover (~**4h** stale at boot on volume); snapshot **write exceeded `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS=480`** (`fly.toml`) — snapshot-write cost class (cap program / Phase 1 telemetry), not resolver pathology.

---

## Related (out of stall-guard scope)

`heartbeat stale >420s, restarting loop` — **7** occurrences (`2026-10-10T12:42Z` through `2026-10-11T01:12Z`). Outcome watchdog, not stall-guard strike chain.

---

## Gate snapshot (unchanged)

| Gate | Result |
|------|--------|
| Web / VM FINAL | **PASS** |
| Stall guard (strict `merge-soak-criteria`) | **GUARD_FAIL** |

Mitigating facts recorded elsewhere; do not re-infer upgrade from this receipt alone.
