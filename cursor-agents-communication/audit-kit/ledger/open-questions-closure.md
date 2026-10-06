# F02 open production questions — audit closure

**Pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129`  
**PR:** [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324)  
**Sources:** Ditto `67d91e97` (ledger rev 1), `07a7021d` / `17377f38` (rev 2), `95477316` (readiness `published`); [`claims.json`](claims.json); [`f-items-prior-evidence-map-2026-10-03.md`](../f-items-prior-evidence-map-2026-10-03.md) appendix REV 2.2  
**Compiled:** 2026-10-06 (Mission Control unknowns-closure workstream 5/5)

Revision 1 tracked **14** open production questions (O1–O14). Revision 2 closed three, narrowed several, and added **O15–O18** from live probing. This table maps each row to an existing `claim_id`, a named evidence row, or an explicit **NOT_OBSERVABLE** / **UNVERIFIED** boundary at the audit pin.

## Summary counts

| Scope | closed | bounded | open | Total |
|---|---:|---:|---:|---:|
| **O1–O14** (original F02 set) | 4 | 7 | 3 | 14 |
| **O15–O18** (rev 2 additions) | 0 | 4 | 0 | 4 |
| **All O1–O18** | **4** | **11** | **3** | **18** |

**Status vocabulary**

| Status | Meaning |
|---|---|
| **closed** | Receipt at pin or authorized public GET closes the question for audit purposes |
| **bounded** | Mechanism or static scope settled; remainder explicitly **NOT_OBSERVABLE** (no Gate C probe taken) or **UNVERIFIED** (source-only) |
| **open** | No sufficient receipt; authorized probe still required |

---

## Closure table — O1–O14 (original)

| id | question (short) | status | evidence link | next authorized probe (if any) |
|---|---|---|---|---|
| **O1** | Orphaned pool threads / OOM after cycle timeouts (#1113) | **bounded** | `claim_id` **C4-FLOCK-SPINLOCK-001** + issue **#1113**; evidence map REV 2 §F02 (per-cycle executor, not persistent pool); Ditto rev 2: `_abandoned_live=0` across 10 live cycles | Gate C: time-separated `py-spy` / thread census by `thread_name_prefix` (≥12h apart). **NOT_OBSERVABLE** at audit time (no Fly exec). |
| **O2** | 101s `persist_summary_rmw` latency split | **closed** | `claim_id` **C13-CHECKPOINT-T1_5-001**; PR **#1173** merged 2026-09-03; public `GET /api/soul-map` `cycle_history` (Ditto rev 2: max stage ~1040ms, not 101s) | None — re-probe optional if deploy pin changes. |
| **O3** | On-disk `soul_map.json` size / staleness | **closed** | Evidence row **EOQ-O3** (Ditto rev 2 live probe: **840,123 bytes**; refutes 24.2MB claim) | None at pin. |
| **O4** | Per-key `soul_map` byte census | **bounded** | **EOQ-O4** — payload granularity sufficient (file ≈0.84MB); per-key breakdown needs `scripts/soul_map_census_readonly.py` on volume | Gate C: `fly machine exec` census. **NOT_OBSERVABLE** from public endpoints. Low priority. |
| **O5** | Cold-start `0 subnets` boot race | **open** | **UNVERIFIED** — Gemini mechanism (empty `_SUBNETS_CACHE` during boot sleep) is source-reading only (Ditto §0.3) | Gate C: cold-start capture with traceback before first TMC fetch completes. |
| **O6** | Resolver scheduler cadence (nominal 15m) | **closed** | **EOQ-O6** — Ditto rev 2: 15m cadence holding, `cycle_history` present on `/api/soul-map` | None for current cadence. |
| **O7** | Historical resolver cadence stretch (~82.6 min) | **bounded** | **EOQ-O7** — current cadence covered by O6; historical stretch never diagnosed | Gate C: log soak / telemetry timeline. **NOT_OBSERVABLE** from 2026-10-04 public GETs. |
| **O8** | Four universe cardinalities disagree (168 / 129 / 124 / 75) | **open** | **EOQ-O8** — Ditto rev 2 simultaneous probes; partial static overlap **C9-TOP-SCORING-UNIVERSE-001** (scoring cap, not feed count); Replit 2026-10-04: 168 `/api/subnets` entries | Gate C: re-probe `/api/subnets` + `/api/ops/readiness` `subnet_feed` on same timestamp; define single authoritative universe provider (product decision). |
| **O9** | `id` vs `netuid` key divergence beyond PR #1293 | **open** | **EOQ-O9** — `netuid_of()` pattern at `internal/subnets/summary.py:15-24`; PR **#1293** HOLD | Static: AST/route audit for endpoints not using `netuid_of()`. No prod probe required for scope enumeration. |
| **O10** | Blocking calls in `async def` routes beyond PR #710 | **bounded** | Rev 1 **C2** (TaoStats `time.sleep` in `_rate_limit`, `fetchers/taostats_client.py:92-101`); **C5-SQLITE-INVENTORY-001** (sqlite sites). Full call-graph **UNVERIFIED** | Static: AST call-graph from async handlers (authorized local Gate A). Not a prod probe. |
| **O11** | Hot SQLite caches bypass WAL helper | **bounded** | `claim_id` **C5-SQLITE-INVENTORY-001** (10 prod `sqlite3.connect` sites); rev 1: `chain_client.py` ×5, `investigation/service.py` ×3 bypass `fetchers/_sqlite.py` | Gate C: `PRAGMA journal_mode` per live DB + `database is locked` frequency. **NOT_OBSERVABLE** at audit time. |
| **O12** | F1 score-snapshot producer / drift / kill path | **bounded** | `claim_id` **C4-REVIVED-LATCH-001**, **C4-FLOCK-SPINLOCK-001**; evidence map REV 2: same-process second-build window **contradicted** (`_write_future_active()`); lazy periodic registration after revive remains source-supported | Gate C: confirm kill path fires (`loop_stall_guard.py:178-217`, `score_snapshots.py:836-860`); effective **LOOP_STALL_GUARD_KILL** value. **NOT_OBSERVABLE** (fly.toml silent; code default True). |
| **O13** | Worker restart double-writer on `/app/data` | **bounded** | Evidence map REV 2 §F02 — `fly_web_entrypoint.sh:55-56` `kill` → `_start_inline_worker`; overlap duration **NOT_OBSERVABLE** | Gate C: overlapping worker PIDs during supervisor restart; link to O11 contention hypothesis. |
| **O14** | “296 bare `except`” count | **closed** | `claim_id` **C8-BARE-EXCEPT-PASS-001** — AST at pin: **299 typed `except`+`pass`, bare=0** (refutes “296 bare except”) | None at pin. |

---

## Closure table — O15–O18 (rev 2 additions)

| id | question (short) | status | evidence link | next authorized probe (if any) |
|---|---|---|---|---|
| **O15** | `/api/simivision` flips between rows and `source:busy` | **bounded** | Ditto rev 2 §3.1: **REFUTED** `_WEIGHED_BUILD_LOCK` theory; `busy` = cold `_SIMIVISION_CACHE` (`_build_simivision_cached`), not lock contention | Gate C: timestamped paired probes when `busy` observed. Mechanism bounded at source. |
| **O16** | Effective write timeout vs stuck threshold (O12 dependency) | **bounded** | Source at pin: `WRITE_TIMEOUT_SECONDS=480`, `SCORE_SNAPSHOT_STUCK_SECONDS=900`; `fly.toml:48` `RESOLVER_CYCLE_TIMEOUT_SECONDS=360` (committed, effective runtime **NOT_OBSERVABLE**) | Gate C: read effective env on live machine. |
| **O17** | Ops `published:false` while `/api/daily-pick` serves pick | **bounded** | **EOQ-O17** + adjacent **C7-READINESS-GRADED-FALLBACK-001**; Ditto `95477316`: `readiness.py:37` reads missing `published` key from `daily_pick_engine` payloads | Product fix (one-line readiness) — out of audit evidence PR scope. |
| **O18** | Readiness `daily.published` always false | **bounded** | Same as O17 — schema gap, cosmetic at sole consumer (`readiness.py:268` HOLD-only branch) | None for audit closure; optional code fix tracked separately. |

---

## Evidence rows (no `claim_id` — ledger cross-refs only)

| row_id | closes / bounds | receipt |
|---|---|---|
| **EOQ-O3** | O3 | Ditto rev 2: 840,123 bytes on disk (2026-10-02 live probe) |
| **EOQ-O4** | O4 | File ≈0.84MB; per-key census deferred |
| **EOQ-O6** | O6 | `/api/soul-map` `prediction_resolver_scheduler.cycle_history` — 15m cadence |
| **EOQ-O7** | O7 | Historical stretch UNVERIFIED; O6 closes current state |
| **EOQ-O8** | O8 | 2026-10-02: `/api/subnets` 168 vs readiness `registry_count` 75 / `live_cache` 124 / `tmc_cache` 129 |
| **EOQ-O9** | O9 | PR #1293 + `netuid_of()` anchor at pin |
| **EOQ-O17** | O17, O18 | Ditto `95477316` — `published` key absent from engine payloads |

---

## REV 2.2 appendix cross-walk

Provenance edges in [`f-items-prior-evidence-map-2026-10-03.md`](../f-items-prior-evidence-map-2026-10-03.md) (appendix REV 2.2) map F02 / #1113 / Ditto memories → `claim_id`s. This closure table is the **question-axis** inverse:

| claim_id | open_questions |
|---|---|
| C4-FLOCK-SPINLOCK-001 | O1, O12 |
| C4-REVIVED-LATCH-001 | O12 |
| C13-CHECKPOINT-T1_5-001 | O2 |
| C5-SQLITE-INVENTORY-001 | O11 |
| C8-BARE-EXCEPT-PASS-001 | O14 |
| C7-READINESS-GRADED-FALLBACK-001 | O17, O18 |
| C9-TOP-SCORING-UNIVERSE-001 | O8 (partial — scoring cap, not feed cardinality) |
| L2-PERSIST-HYDRATE-001 | O2 (hypothesis context), O5 (boot wedge hypothesis) |

**UNMAPPED / ticket missing (REV 2.2):** C-015, C-016 (queue artifacts only); C-017 absent — do not invent bundles.

---

## Audit closure rule

No “investigation phase complete” for F02 runtime unknowns until every **open** row above moves to **closed** or **bounded** with a named receipt. At pin `ce3d8200`, **3 open** (O5, O8, O9) and **11 bounded** rows carry explicit **NOT_OBSERVABLE** or **UNVERIFIED** boundaries rather than silent assertion.
