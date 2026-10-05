# Brief for Cursor — Subnet Dashboard, Lanes 1 & 2

**Repo:** cryptoreporthub/subnet-dashboard  
**Target pin:** `ce3d820013d45577333ac8aada8c0d9e97c54129` (matches live `/version`)  
**Scope:** Two lanes running in parallel.

- **Lane 1:** Deep static code audit (read-only, exhaustive against C1–C13 contradiction classes with stop rule).
- **Lane 2:** Live runtime investigation (2026-10-05 ~26-minute service degradation window 08:29Z–08:55Z UTC and Fly logs under strict governance).

**Bootstrap:** Read `cursor-agents-communication/audit-kit/README.md` and the kit files before the population ledger or map fold-in.

I authorize:

1. **Map fold-in:** absorb Audit v2.7.1 settled core into `cursor-agents-communication/audit-kit/f-items-prior-evidence-map-2026-10-03.md`.
2. **Pin decision:** re-pin F02 strictly to `ce3d820013d45577333ac8aada8c0d9e97c54129`.

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

---

## Lane 2 — Live Runtime Investigation (Governance Envelope)

**Work:** Investigate the **2026-10-05 ~26-minute service degradation** (08:29Z–08:55Z UTC) and examine Fly logs against the live service.

### Authority envelope (strict boundaries)

| # | Action class | Granted? | Boundary |
|---|---|---|---|
| L2.1 | Read-only endpoint pulls (`GET` to `/health`, `/api/*`) | **YES** | No mutation; no query params that trigger writes; no retry storms. |
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
3. **Lane 2 incident report:** Root cause of the 2026-10-05 08:29Z–08:55Z UTC degradation supported by Fly logs and process inspection.
4. **CI regression guards:** Proposed automated tests or lint rules for every confirmed defect (proposal only; no implementation in this project unless separately authorized).

---

## Appendix: Unverified candidates to re-derive (do not trust without receipts)

- **C1:** `MAX_SNAPSHOTS` 600 vs 60; `_LEARNING_MIN_WEIGHT` 0.3 vs 0.1 (check liveness in import graph).
- **C2:** `WATCHLIST_PATH` config/ vs data/; `WORKER_PEER_TIMEOUT_SECONDS` 4 vs 12; `HOMEPAGE_SHELL_CACHE_SECONDS` 60 vs 45.
- **C4:** `internal/loop_stall_guard.py` `revived` and `resolver_revived` un-reset flags; 5.0s `flock` spinlocks in `score_snapshots.py`, `daily_pick_engine.py`, `price_fetcher.py`, `predictions_store.py`, `soul_map_io.py`.
- **C5:** All `sqlite3.connect` sites at `ce3d820013d45577333ac8aada8c0d9e97c54129` — classify managed vs unmanaged; read `PRAGMA journal_mode` on disk under L2.3 where needed.
- **C8:** `resolver_scheduler.py:736` and `:1181` `write_soul_map` wrapped in `except Exception: pass` (trace downstream status).

Confirm receipt and begin Lane 1 ledger and Lane 2 log inspection.
