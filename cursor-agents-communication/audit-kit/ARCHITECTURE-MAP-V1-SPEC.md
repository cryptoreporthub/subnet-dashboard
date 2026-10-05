# Architecture Map v1 — merged spec (Joshua brief + MC corrections)

**Pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129`  
**Evidence PR:** [#1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) · branch `cursor/audit-evidence-2026-10-05-smoke`  
**Authoritative review surface:** Replit PR comments (`review_status` source of truth = Replit)

---

## Purpose

Single merged charter for the **live architecture map** (Layers 1–4) and the **historical provenance map** (REV 2.2 appendix). Joshua brief = [`subnet-dashboard-audit-brief.md`](subnet-dashboard-audit-brief.md). MC corrections below override any stale prose in prior drafts or agent chat.

---

## Two-diagram model

| Diagram | File | Scope | When |
|---|---|---|---|
| **Live map** | [`ledger/candidate-matrix.md`](ledger/candidate-matrix.md) | Runtime topology + request/data flow at pin | **L1+L2 now**; L3 table+hazard later; L4 timeline+annotations later |
| **Historical map** | [`f-items-prior-evidence-map-2026-10-03.md`](f-items-prior-evidence-map-2026-10-03.md) appendix | F02/issues/Ditto mem → claim_id provenance | Full **REV 2 re-read** for Replit Batch B |

**SimiVision stack box:** include in L3 hazard layer (council → picks → resolver → grading → cockpit hydrate). L1+L2 name the stack boundary only; do not draw full L3 hazard edges until Batch 2 closes.

---

## Layer defaults (Phase 1)

| Layer | Deliver now? | Contents |
|---|---|---|
| **L1 — Topology** | **Yes** | Fly single machine, one Uvicorn process, volume, env, boot threads, external feeds, data-asset inventory |
| **L2 — Request / data flow** | **Yes** | HTTP + hydrate fan-out, persist paths, lock domains, load_shed/rate_limit, worker volume proxy, incident windows A/B/C tags |
| **L3 — Hazard / contention** | **Later** | Master table + hazard diagram (flock convoy, thread-pool wedge, static burst vs API) |
| **L4 — Timeline** | **Later** | Incident A/B/C annotations on nodes; boot-hydrate vs `/health` 200 sequence |

---

## Phase 1 deliverables (audit kit)

1. **Population ledger** — `ledger/population.tsv` (1413 files, stop-rule 2/2 PASSED)
2. **Evidence bundles** — `findings/*.json` (26 claim_ids indexed)
3. **Claim index** — `ledger/claims.json` (MC-only writes; Replit sets `review_status`)
4. **Live diagram L1+L2** — `ledger/candidate-matrix.md` + master table (26 rows)
5. **Merged spec** — this file
6. **Historical appendix** — REV 2.2 provenance graph at end of evidence map
7. **Replit Batch 2 brief** — [`REPLIT-BATCH2-BRIEF.md`](REPLIT-BATCH2-BRIEF.md)
8. **Lane 2 incident index** — `ledger/incidents.json` + L2 bundles (A/B/C + persist/hydrate)
9. **CI regression guard proposals** — proposal-only; no implementation in evidence PRs

---

## Master table columns (candidate-matrix)

Every indexed claim_id gets one row:

| Column | Meaning |
|---|---|
| `claim_id` | Ledger key |
| `layer` | L1 / L2 / L1+L2 / historical |
| `runtime_subsystem` | e.g. fly-topology, persist-rmw, client-hydrate |
| `code_anchor` | `path:lines` at pin (git show) |
| `data/asset` | JSON/SQLite/lock file touched |
| `incident` | A / B / C / — |
| `disposition` | From bundle |
| `review_status` | **Replit PR comment** (`pending` / `replit_pass` / `replit_modify` / `replit_block`) |
| `map_provenance` | live-matrix / f-items-map / bundle-only |
| `verified_at_sha` | Pin or PR head when Replit PASS |
| `evidence_tier` | B default; A only after Joshua |
| `contradicted_by` | Other claim_id or REV2 note |
| `campaign_ticket` | Ditto id / issue # / — |
| `execution_context` | web-asgi / boot-thread / inline-worker / ap-scheduler / client-hydrate / volume-rmw |
| `blocks_loop` | yes / no / unknown |

---

## Embedded corrections (mandatory — do not regress)

| Topic | Wrong | Correct at pin |
|---|---|---|
| **Predictions persist** | "Unlocked resolver write" | `resolver._save_json` uses `locked_predictions_file()` — `resolver.py:215-216`. **Two lock domains:** `predictions.json.lock` (predictions flock) vs `soul_map.json.lock` (soul_map flock). Not the same domain. |
| **Hourly vs daily pick** | "Hourly always long" | Hourly **HAS HOLD** — `hourly_pick.py:86` (empty universe), `:139` (confidence/directional gate). Daily candidate is **always long** — `daily_pick.py:284`. |
| **Campaign tickets** | C-017 | **C-017 does NOT exist** in repo. Only `queue/done/C-015.json`, `queue/done/C-016.json`. Map C-017 as **ticket missing**. |
| **Cockpit cap env** | `COCKPIT_PICKS_REGISTRY_HOUR_CAP` | **`COCKPIT_PICKS_REGISTRY_CAP`** — `picks_snapshot.py:16` (Python var `_REGISTRY_HOUR_CAP` reads this env). |
| **Worker proxy weights** | Silent 1.0 defaults | `load_weights_for_ui` returns **`_proxy_degraded`** — `weights.py:542-560`; callers must not treat as learned 1.0. |
| **Fly topology** | Separate worker VM | **`fly.toml` single `web` process** owns inline worker + `[mounts] data_volume` → `/app/data`. No second process group in v1. |
| **Replit gate** | Chat / Ditto memory | Replit executes **Batch 2 via PR comments** on #1324. **`review_status` in `claims.json` is updated from Replit comments only** (MC mirrors). |

Additional REV 2 drops (historical map only): persistent resolver `ThreadPoolExecutor` pool (refuted — per-cycle pool at `:828`); "~50-second freeze" informal label (use 08:29–08:55Z Incident A window).

---

## Batch 2 scopes (Replit)

See [`REPLIT-BATCH2-BRIEF.md`](REPLIT-BATCH2-BRIEF.md). Summary:

| Scope | Subject | SATISFIED | BLOCKED |
|---|---|---|---|
| **A** | Ledger ↔ findings consistency | Every `claim_id` has bundle; pin matches; schema valid | Missing bundle, pin drift, schema fail |
| **B** | Evidence map REV 2 at pin | git-show confirms REV 2 corrections | Line drift or new contradiction class |
| **C** | candidate-matrix ↔ ledger | 26 rows; dispositions/status align | Row missing or mismatch |
| **D** | git-show gating claims | PASS/MODIFY/BLOCK per gating claim_id | Unreproducible command output |

**17 pending claim_ids** (Batch 2 primary workload) — all with `review_status: pending` in `claims.json` as of Day 1 close.

---

## DROP list (do not promote to Tier A without re-derive)

| Drop | Reason |
|---|---|
| Persistent resolver executor pool / slot hoarding | REV 2 refuted — fresh per-cycle pool |
| Separate Fly worker machine for schedulers | v1 inline worker on web process |
| Unlocked `predictions.json` writes from resolver | `locked_predictions_file` at `resolver.py:215-216` |
| C-017 campaign ticket | File absent; only C-015/C-016 in `queue/done/` |
| `COCKPIT_PICKS_REGISTRY_HOUR_CAP` env name | Wrong; use `COCKPIT_PICKS_REGISTRY_CAP` |
| Proxy failure → silent 1.0 council weights | `_proxy_degraded` contract |
| "~50-second freeze" as second incident | Retired label; use Incident A window |
| Gemini on critical review path | Ditto Code blind parallel + Replit PR comments |
| Claude Sonnet as audit gate | Per model guide — Grok MC + Replit + Joshua |

---

## Ditto finish-slice trigger

After Replit Batch 2 **PASS** on L1+L2 anchor claims (`SMOKE-001`, `SMOKE-002`, `C6-WORKER-HEAVY-ESSENTIAL-001`, L2 incidents A/B/C, `L2-PERSIST-HYDRATE-001`), MC posts [`DITTO-TICKET-L1L2.md`](DITTO-TICKET-L1L2.md) at **PR head SHA** per [`DITTO-HANDOFF.md`](DITTO-HANDOFF.md). Ditto commits blind parallel bundles to PR head only.

---

## Team (execution)

| Seat | Role |
|---|---|
| **Cursor / MC** | Docs, ledger index, diagram, PR |
| **Replit** | PR spot-check gate — PASS / MODIFY / BLOCK in comments |
| **Joshua** | Tier B→A + merge |
| **Ditto** | Blind parallel after each meaningful slice (handoff ticket at end) |

**Do not use Claude as gate.**
