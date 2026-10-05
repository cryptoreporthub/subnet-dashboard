# Brief for Cursor — Subnet Dashboard, Lanes 1 & 2

**Repo:** cryptoreporthub/subnet-dashboard  
**Target pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129` (matches live `/version`)  
**Scope:** Two lanes running in parallel.

- **Lane 1:** Deep static code audit (read-only, exhaustive against C1–C13 contradiction classes with stop rule).
- **Lane 2:** Live runtime investigation — **three distinct 2026-10-05 UTC production windows** (Fly logs under strict governance):
  - **Incident A:** event-loop wedge **08:29Z–08:55Z** (~26 minutes; Ditto `93d36426`)
  - **Incident B:** connection-timeout wedge **11:41:30Z–11:47:23Z** (~6 minutes; Gemini task-279 / user report)
  - **Incident C:** static-asset wedge **11:49:15Z** (post-recovery browser load failure; Gemini task-279 / user report)

**Do not conflate with Lane 1 audit-run timestamps:** a separate **Lane 1 ledger read span** on the same calendar day was **02:09:49–02:10:13 UTC** (clean `READ` frames only; emits after **02:10:14** are error tail with no audit weight). That span is provenance for static anchors (e.g. `server.py:632` / `:3251` pending independent re-read), **not** the production incident window.

**Retired label:** “~50-second freeze” was informal shorthand (Ditto Definition A, memory `40bb3345`) and contradicts the measured **08:29Z–08:55Z** window (Gemini/Ditto receipt `93d36426`, ~25–26 minutes, self-recovered InstantBailout wedge). It is **not** a second incident unless separately receipted.

**Bootstrap:** Read `cursor-agents-communication/audit-kit/README.md` and the kit files before the population ledger or map fold-in.

I authorize:

1. **Map fold-in:** absorb Audit v2.7.1 settled core into `cursor-agents-communication/audit-kit/f-items-prior-evidence-map-2026-10-03.md`.
2. **Pin decision:** re-pin F02 strictly to `ce3d820013d45577333ac8aada8c0d9e97c54129`.

---

## Project model — Mission Control + two lane agents

Adapted from Architecture Epistemics (PR #1294 campaign); **not** a full 3-seat
Grok fleet. Follow-up to audit-kit handoff [PR #1322](https://github.com/cryptoreporthub/subnet-dashboard/pull/1322).

| Role | Cursor Project seat | Does | Does not |
|---|---|---|---|
| **Mission Control** | Project coordinator (you talk here) | Routes tickets to Lane 1 / Lane 2; strip-validates Evidence Bundles; merges into candidate matrix; Ditto writes (`source=cursor`); holds Tier **B→A** until Joshua spot-check | Fetch product code; run Lane 2 probes; product fixes |
| **Lane 1** | Background worker | Tracer: pin bytes, population ledger, C1–C13, bundles → `audit-kit/findings/` | Live probes; merge-desk prose; implementation |
| **Lane 2** | Background worker | ConfigTruth: L2.1–L2.3 receipts only; Incidents A/B/C timelines; bundles → `audit-kit/findings/` | Code census; repo edits; deploy |

**Gemini:** blind parallel C1–C13 (capture–recapture) — **not a seat**.  
**Ditto:** coverify on request — **not a seat**, never the merge desk.

**Routing rules (MC only):**

1. Workers return **Evidence Bundle JSON files only** — no seat-to-seat prose DMs.
2. MC rejects bundles missing required fields (see `evidence-bundle-schema.md`).
3. Conflicting bundles stay Tier **B** until Joshua resolves; both kept on disk.
4. Chronology before causality: establish incident timestamps (Lane 2) before mechanism claims.
5. Never skip a scoped item because a plausible upstream fix exists elsewhere.

**Kickoff line for the new Project:**

> You are Mission Control. Spawn Lane 1 and Lane 2 workers per this brief. Seats
> return bundles to `cursor-agents-communication/audit-kit/findings/` only.

---

## Epistemics guardrails (mandatory)

### SMOKE gate — before full census

Do **not** open hard claims or the full 1413-file ledger until SMOKE passes at
`ce3d820013d45577333ac8aada8c0d9e97c54129`:

| ID | Check | PASS = |
|---|---|---|
| SMOKE-001 | `server.py:510-512` | Literal `StaticFiles` mount at `/static` |
| SMOKE-002 | `resolver_scheduler.py:736` | `write_soul_map` still wrapped in `except Exception: pass` (or disposition updated with receipt) |
| SMOKE-003 | `/version` vs pin | Live `/version` SHA equals charter pin (Lane 2.1, one GET) |

FAIL any SMOKE → stop; fix charter/pin mismatch before census.

### Evidence Bundles on disk

- Schema: [`evidence-bundle-schema.md`](evidence-bundle-schema.md)
- Output: [`findings/`](findings/)
- Every **CONFIRMED** finding → JSON bundle + candidate-matrix row
- **Tier B** default; **Tier A** only after Joshua spot-check of gating citations
- Old `queue/done/*.json` at pin `c9449d64…` — historical; re-verify at `ce3d8200` before Tier A (see C-016 drift caution)

### Implementation phase (after audit)

Adversarial single-PR review: **PASS / MODIFY / BLOCK** per fix PR. Separate
authorization from this read-only audit (Rule 8).

---

## Lane 1 — Deep Static Code Audit (Full Scope)

**Work:** Complete, exhaustive sweep of every tracked file against 13 finite contradiction classes to eradicate internal code conflicts. Read-only against pinned commit `ce3d820013d45577333ac8aada8c0d9e97c54129`.

### 1. Population ledger

- Every tracked file (all **1413** files in `git ls-tree -r --name-only ce3d820013d45577333ac8aada8c0d9e97c54129`, not only `.py`).
- Ledger schema per file: `[Path] | [Blob SHA] | [Bytes] | [Lines] | [Classes Scanned] | [READ / UNREAD / PARSE-FAIL]`.
- Report denominators.

### 2. The 13 contradiction classes (C1–C13)

Per class: detector, candidate list, and disposition (`CONFIRMED / REFUTED / BY-DESIGN / UNKNOWN`) with a falsifier.

- **C1 Duplicate definitions:** Same-name constants/functions with diverging values (e.g. candidate `_LEARNING_MIN_WEIGHT` 0.1 vs 0.3, `MAX_SNAPSHOTS` 60 vs 600) plus import-graph liveness.
- **C2 Config divergence:** Every env var × default × `fly.toml` × type/units (e.g. `WATCHLIST_PATH` config vs data, `WORKER_PEER_TIMEOUT_SECONDS` 4 vs 12).
- **C3 Dead vs live:** Unreferenced symbols and dead code reached by lazy dynamic imports.
- **C4 Guards and feedback:** Every watchdog, timeout, retry, latch, revive, and kill-switch. Thresholds vs actual task cadences (e.g. `loop_stall_guard.py` latches, 5.0s `flock` spinlocks).
- **C5 State ownership and locks:** Writers, process boundaries, locking primitives (`flock`, `threading.Lock`), RMW overhead, and SQLite connections. **Re-derive at `ce3d820013d45577333ac8aada8c0d9e97c54129`; define “unmanaged” vs WAL-managed; do not trust prior counts.** Prior Cursor spot-check at this pin: **10 production** `sqlite3.connect` call sites (`internal/chain_client.py:41,442,452,467,479`; `internal/investigation/service.py:80,94,112`; `fetchers/_sqlite.py:28`; `message_intel/models.py:32`) plus **1 test** site (`tests/test_message_intel_reset.py:65`). Lane 2.3 may read `PRAGMA journal_mode` on disk where authorized.
- **C6 Boot and arming:** Trace `WORKER_HEAVY="essential"` vs `is_worker_mode()` boot paths for all schedulers.
- **C7 Labels vs values:** Dashboard metrics and `/api/ops/*` statuses traced to underlying calculations.
- **C8 Silent failure:** AST exception swallows (`except: pass`) classified as benign vs hazardous.
- **C9 Limits and slices:** Every `[:N]`, `min/max`, and cap.  
  *NOTE: User-declared intent (Top-10 subnet exclusion) is BY-DESIGN. Audit whether implementation honors declared intent without regressing snapshot ranking.*
- **C10 Historical claims:** Comments and docstrings parsed as claims (“only”, “never”, “always”) and checked against code.
- **C11 Tests:** Conflicting tests pinning contradictory behaviors.
- **C12 Resource traces:** File descriptors, thread lifecycles, and connection pooling.
- **C13 Phase checkpoints:** Cross-phase state consistency and handoff invariants.

### 3. Stopping rule and coverage

- Stratified random sample of 30 files read in full. Any anomaly outside C1–C13 creates a new class.
- Audit terminates only when **two consecutive random samples of 30 files yield zero new classes**.
- Sampling and detector overlap assess coverage and blind spots; they do not constitute a mathematical guarantee of zero defects.

### 4. Independence

- Gemini runs C1–C13 blind in parallel to compute capture–recapture overlap and expose blind spots.
- Agent agreement is not independent corroboration; Ditto-origin receipts stay Ditto-origin until re-verified at the pin.

### 5. Operational guardrails

- Transport and blob SHA on every receipt. Scanner output is candidates only.
- No agent summary counts as evidence. Product intent comes only from the user’s declared list; otherwise UNKNOWN.
- Confirmed defects are audit output only. **Implementation** (including SQLite WAL/locking and multi-process volume behavior) is a separate authorized phase.

### 6. Lane 1 provenance note (do not paraphrase)

> Provenance note: the `ce3d820013d45577333ac8aada8c0d9e97c54129` ledger produced clean `READ` frames from **2026-10-05 02:09:49–02:10:13 UTC** (source of the `:632` / `:3251` anchors). Emits after **02:10:14 UTC** are error output and carry no audit weight in either direction.

This note closes Lane 1’s governance artifact only. It is **not** the Lane 2 incident clock. Lane 2 correlates the three windows in § Lane 2 priority evidence below.

---

## Lane 2 — Live Runtime Investigation (Governance Envelope)

**Work:** Investigate all **2026-10-05 production degradation windows** under the L2 envelope. Correlate Fly logs and read-only probes across incidents — do not treat them as one undifferentiated outage.

### Lane 2 priority evidence (Gemini-origin — user-authorized for audit)

**Status:** symptoms and timestamps are **priority Lane 2 evidence**; root-cause mechanism is **UNVERIFIED** until independently receipted. Ditto memory `750072ef` notes pushback: CSS timeout → blank page is not standard browser behavior; `ui.css` empty-body vs 503 KB mismatch needs reconciliation; “45 blocking reads starve Uvicorn” remains a **candidate**, not a confirmed mechanism.

#### Incident A — morning event-loop wedge (Ditto `93d36426`)

- **Window:** **08:29Z–08:55Z UTC** (~26 minutes)
- **Symptom:** HTTP hangs (>15s), process alive, self-recovered without restart — InstantBailout / synchronous-work-on-loop class (not novel)
- **Correlated:** GitHub Actions uptime curl `000000` at **08:44Z** (`2d479104`) inside this window

#### Incident B — mid-day connection freeze (Gemini task-279 / user report)

- **Window:** **11:41:30Z–11:47:23Z UTC** (~6 minutes)
- **Symptom:** live site not loading; **48 consecutive health probes timed out** (per Gemini/user report — re-derive under L2.1/L2.2)

#### Incident C — static-asset wedge (Gemini task-279 / user report)

- **Window:** **11:49:15Z UTC** (after `/` returned 200)
- **Symptom:** browser still failed to load — **static asset queuing starvation** (Gemini label; mechanism UNVERIFIED)
- **Gemini raw reproduction (Ditto `750072ef`, task-279):** homepage requests **45** simultaneous CSS/JS assets; sample:
  - `/static/favicon.svg` → 200 (607 B)
  - `/static/css/smoke-tokens.css` → 200 (6.4 KB)
  - `/static/css/base.css` → **FAILED** (connection timed out >5s)
  - `/static/css/ui.css` → 200 (**503 KB** per Gemini; pin blob **503,871 bytes** at `ce3d8200`)
  - `/static/css/tribunal-hero-layout.css` → **FAILED** (connection timed out >5s)
- **Pin-verified architecture (Cursor, same-turn at `ce3d8200`):**
  - `server.py:510-512` — `app.mount("/static", StaticFiles(directory=_static_dir), name="static")`
  - **47** unique `/static/…` paths referenced across `templates/` at pin (Gemini’s **45** is consistent within counting tolerance)
  - `static/css/base.css` = **9,469 bytes**; `static/css/tribunal-hero-layout.css` = **1,609 bytes**

**Lane 1 ↔ Lane 2 correlation (mandatory):**

1. **C5 & C12:** How is Starlette/FastAPI `StaticFiles` mounted and served? Can synchronous static I/O contend with API/background work on the single Fly web process? File-descriptor and connection lifecycle under burst parallel `/static/*` loads.
2. **Lane 2 logs:** Fly logs for **11:41:30Z–11:47:23Z** — what synchronous task/lock held the process before/during the static asset storm at **11:49:15Z**?
3. **Mechanism falsifiers:** If static files serve in <1s while `/health` times out, queuing-starvation is refuted; if `ui.css` returns 200 with zero-byte body (Ditto live probe in `750072ef`), investigate streaming/truncation separately from timeout theory.

### Cursor action item — persist pipeline & background hydrators (mandatory audit scope)

**Goal:** Determine whether the **persist pipeline** and **background hydrators** can **block the ASGI event loop** when upstream subnet/universe feeds return `status=timeout` — and map every path where timeout handling still runs synchronous work on the web process.

**This is audit scope only** (Lane 1 C4/C5/C12 + Lane 2 correlation). **Not a code fix in PR #1322.** Implementation and deploy are a **separate authorized phase** after confirmed defects.

**Pin-anchored starting points at `ce3d820013d45577333ac8aada8c0d9e97c54129` (re-verify same-turn):**

| Area | Receipt | Audit question |
|---|---|---|
| Persist RMW | `internal/store/soul_map_io.py:47-69` (`fcntl` spin up to 5s); `resolver_scheduler.py:735,1176` (`write_soul_map`); `:392-393` (`persist_summary_rmw_ms` telemetry) | Does persist hold the loop or thread pool while subnet upstream is degraded? |
| Resolver cycle | `internal/council/resolver_scheduler.py` persist wrapped in `except Exception: pass` at `:736` / `:1181` (C8 appendix) | Silent persist failure vs continued blocking work when feeds time out |
| Subnet timeout surface | `server.py:1842-1848` (`/api/subnets` handler timeout → `status="timeout"`); `:2588-2926` hydrate paths (`HYDRATE_SUBNETS_TIMEOUT_SECONDS` default 4s) | Does `status=timeout` short-circuit async paths or fall through to sync rebuild? |
| Background hydrators | `server.py:310-361` boot threads (`homepage-warm-boot`, `registry-name-sync`, `council-weight-rebalance`, `background_boot.start_background_workers`); `:363-368` capped `AIO_WORKER_POOL_SIZE` default 4 | Do boot/hydrate threads contend with request-path work on the same process? |
| Inline worker proxy | `server.py:973-975`, `:1476-1478` (`fetch_worker_json_sync` on request-adjacent paths) | Sync worker RPC while web ASGI loop is wedged? |
| Universe refresh | `internal/subnet_universe.py` (`ensure_background_refresh`, probe budget) | Serial probe + timeout → permanent `degraded` while sync work continues? |

**Required disposition:** For each path: `CONFIRMED` loop-blocker / `REFUTED` (offloaded to thread with bounded timeout) / `BY-DESIGN` / `UNKNOWN`, with falsifier and Lane 2 log correlation for Incidents A–C.

**Deliverable add-on:** One subsection in the Lane 2 incident report titled *Persist/hydrate vs ASGI wedge* linking timeout status emissions to any synchronous work still running on the web process during **11:41–11:47Z** and **08:29–08:55Z**.

### Authority envelope (strict boundaries)

| # | Action class | Granted? | Boundary |
|---|---|---|---|
| L2.1 | Read-only HTTP GET (`/health`, `/`, `/static/*`, `/api/*`) | **YES** | No mutation; no query params that trigger writes; no retry storms. |
| L2.2 | Log reads (`fly logs`, log tail on machine) | **YES** | Read-only stream; no log clearing or rotation. |
| L2.3 | Non-mutating `fly machine exec` | **YES** | Hard-bounded inspection only (`ps`, `env`, `cat` logs/config, `netstat`, `ss`). Must not write, install, kill, or restart anything. Record raw output and proof of non-mutation. |
| L2.4 | Restart / redeploy machine | **NO** | Strictly forbidden. Requires separate explicit authorization. |
| L2.5 | Mutate environment / secrets | **NO** | Strictly forbidden. |
| L2.6 | Write to repo or push a branch | **NO** | Strictly forbidden. Lane 2 is investigation, not remediation. |

**Fence (non-negotiable):** No push, no merge, no label change.

**Receipts required for every Lane 2 action:**

- Command issued, verbatim.
- Timestamp (UTC).
- Raw output, quoted.
- For L2.3: an explicit statement of why the command was non-mutating.

---

## Deliverables and output schema

1. **Population ledger:** All 1413 tracked files at `ce3d820013d45577333ac8aada8c0d9e97c54129`.
2. **Candidate matrix per class (C1–C13):** Dispositions and falsifiers.
3. **Lane 2 incident report:** Per-window root-cause analysis for Incidents A (**08:29Z–08:55Z**), B (**11:41:30Z–11:47:23Z**), and C (**11:49:15Z** asset wedge), supported by Fly logs and read-only probes. Label Gemini-origin claims until independently re-verified.
4. **Evidence Bundles:** JSON files in [`findings/`](findings/) per [`evidence-bundle-schema.md`](evidence-bundle-schema.md) — one per CONFIRMED finding.
5. **CI regression guards:** Proposed automated tests or lint rules for every confirmed defect (proposal only; no implementation in this project unless separately authorized).

## Appendix: Unverified candidates to re-derive (do not trust without receipts)

- **C1:** `MAX_SNAPSHOTS` 600 vs 60; `_LEARNING_MIN_WEIGHT` 0.3 vs 0.1 (check liveness in import graph).
- **C2:** `WATCHLIST_PATH` config/ vs data/; `WORKER_PEER_TIMEOUT_SECONDS` 4 vs 12; `HOMEPAGE_SHELL_CACHE_SECONDS` 60 vs 45.
- **C4:** `internal/loop_stall_guard.py` `revived` and `resolver_revived` un-reset flags; 5.0s `flock` spinlocks in `score_snapshots.py`, `daily_pick_engine.py`, `price_fetcher.py`, `predictions_store.py`, `soul_map_io.py`.
- **C5:** All `sqlite3.connect` sites at `ce3d820013d45577333ac8aada8c0d9e97c54129` — classify managed vs unmanaged; read `PRAGMA journal_mode` on disk under L2.3 where needed. **Also:** `server.py:510-512` `StaticFiles` mount — static asset I/O vs API/background contention (Incident C).
- **C8:** `resolver_scheduler.py:736` and `:1181` `write_soul_map` wrapped in `except Exception: pass` (trace downstream status).
- **C12:** Static asset burst load — **47** template-referenced `/static/*` paths at pin; parallel browser fetches vs single-process connection/file-descriptor limits (Incident B/C).
- **C4/C5/C12 cross-cut (action item):** Persist pipeline + background hydrators vs ASGI loop when upstream returns `status=timeout` — see § Cursor action item.

Confirm receipt, run SMOKE gate, then begin Lane 1 ledger and Lane 2 log inspection.
