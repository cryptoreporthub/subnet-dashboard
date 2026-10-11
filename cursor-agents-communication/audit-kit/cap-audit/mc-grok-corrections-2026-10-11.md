# MC Grok corrections — cap-audit adjudication

**Seat:** Grok design/judgment (not a paraphrase of Claude).  
**Adjudicates:** Claude first-pass (parent user paste, 2026-10-11; files opened: `score_snapshots.py`, `pick_scheduler.py`, `subnet_universe.py`, `fly.toml`, ~60% of `server.py`; **not** `scoring_cap.py`, `score_cache.py`, `tradable.py`, CSV).  
**Mechanical pin:** Composer verification **[PR #1354](https://github.com/cryptoreporthub/subnet-dashboard/pull/1354)** @ base `dd195788b3222370be8834a8e2b6cee1cf877524` (verification doc head includes MC MODIFY `bf0d87a1`); `mc-composer-verification-2026-10-11.md`.  
**This branch pin:** `main` @ `dd195788b3222370be8834a8e2b6cee1cf877524` plus this docs commit.  
**CSV / HTML inventory pin:** `9535c3c2a494293f9a11167ee581574f338d2097` — **not** this SHA. Any count, P0 subset, or “352 P0 caps” claim that assumes that CSV without a re-scan at `dd195788` (or later main) is **UNVERIFIED**.  
**Composer file on `main`:** absent at Grok start; **read from sibling branch before this commit.**

Verdict vocabulary: **ACCEPT** / **MODIFY** / **REJECT**. Falsifiers are what would flip the call.

Ditto alignment (read, not restated as new design): background full-eligible snapshot **before** uncap; request handlers score **zero**; `complete` only when succeeded set equals expected membership; otherwise **degraded/partial**, never falsely green; do not raise 90s tick / 480s write timeouts as a substitute for workload proof; web vs worker env remains UNKNOWN without an allowlisted process probe.

---

## Scope / method

| Input | Used as |
|-------|---------|
| Handoff `cursor-cap-audit-handoff.md` Priority #1–#5 + rollout gate | Contract |
| Claude 8 findings + taxonomy D→A→B→C + P0 split + 3-phase rollout | Claims to judge |
| Composer claim table (CONFIRMED 1,2,5; PARTIAL 3,4,6,7,8 per [#1354](https://github.com/cryptoreporthub/subnet-dashboard/pull/1354) @ `dd195788`) + handoff `len(inputs)` **REFUTED** | Byte check, not design |
| `score_snapshots.py`, `scoring_cap.py`, `tradable.py`, `pick_scheduler.py`, `summary.py`, `subnet_universe.py`, `fly.toml`, `server.py` TOP/cap wrappers at `dd195788` | Independent spot-check |
| Ditto `1be445d1`, `2dbeafe1`, `d2c62794` | Sequencing / honesty |

No product code in this PR. No Fly probe. Effective web/worker caps stay **UNKNOWN**.

---

## Composer incorporation (do not upgrade PARTIAL)

| Claude # | Composer | Grok |
|----------|----------|------|
| 1 count / skipped publish still `ok: True` | CONFIRMED | **ACCEPT** |
| 2 swallowed failures | CONFIRMED | **ACCEPT** with wording MODIFY (`except Exception`, not bare `except`) |
| 3 `progress_cb` → `soul_map.json` every 20; `fly.toml` ~101s | **PARTIAL** | **MODIFY** — see §Code |
| 4 rank selector; raising cap ≠ full-active | **PARTIAL** ([#1354](https://github.com/cryptoreporthub/subnet-dashboard/pull/1354)) | **MODIFY** nuance — see §1.4 |
| 5 scheduler `min(24, TOP=20)`; A/B on capped list | CONFIRMED | **ACCEPT** (defaults only; env UNKNOWN) |
| 6 90s tick → `scheduler_hold`; 129 risky | **PARTIAL** | **MODIFY** — timeout/hold CONFIRMED; 129 cost **not encoded** |
| 7 hidden 75 / 0–74 / `MAX_NETUIDS=200` | **PARTIAL** | **MODIFY** |
| 8 `REGISTRY_ONLY` → tiny list; denominator | **PARTIAL** | **MODIFY** — behavior CONFIRMED; universe denominator is **normative** |

Handoff Priority #3 “`count=len(inputs)`”: Composer **REFUTED** as wording. Code is `len(rows)` after `tradable_subnets()` (`score_snapshots.py` ~240, ~286). Semantic intent (count ≠ successful scores) **stands**. Minimal handoff wording fix lands in this PR.

---

## 1. Code findings

### 1.1 Count / `ok: True` on skipped publish — **ACCEPT**

Claude: count is `len(rows)` after `tradable_subnets()`, reported with `ok: True` even when `save_score_snapshot` skips an older stamp.

Matches Composer and `save_score_snapshot` (`incoming < on_disk` → `return` with no write) vs `_build_and_save` always `{"ok": True, "count": payload.get("count")}`.

Aligns handoff Priority #3 **intent** and Ditto honesty: `complete` must not follow `len(rows)` or tick `ok`.

**Falsifier:** a coverage block with `attempted`/`succeeded`/`published` already on the write result and liveness; or skip path returning `ok: False`. Absent at this pin.

### 1.2 Swallowed failures — **ACCEPT** (wording **MODIFY**)

Day/hour loops: `except Exception: pass`. Bad netuid: `continue`. Hour list copied from day when hour scoring is off (`if not score_hour and day_rows: hour_rows = [dict(row) for row in day_rows]`). Related: `score_cache.score_universe` `continue` (Composer; Claude did not open that file — **do not treat as Claude-verified**).

**MODIFY:** say `except Exception: pass`, not “bare `except:`”.

**Falsifier:** failed netuids recorded with stage/error_class; hour rows absent or explicitly `copied_from_day`.

### 1.3 Progress → soul_map / ~101s — **MODIFY** (Composer PARTIAL)

**Keep:** scheduler `progress_cb` every 20 scored rows can RMW full `soul_map.json` (`_progress` → `_persist_cycle_summary` → `weights._load_raw`/`_save_raw`). That is a D-class honesty/load problem on the **snapshot scheduler** path.

**Drop/narrow:**
- Not every `progress_cb` site does soul_map RMW.
- `fly.toml` ~101s `persist_summary_rmw` is the **resolver** cycle comment (containment bump to 360s), same file, **different writer**. Shared-lock contention is plausible; it is **not** proof that snapshot progress caused the 101s or the 36.1s summary RMW in the handoff.

Handoff: prove workload; keep timeout/shared-state investigation **separate** but test contention. Do not bundle resolver compaction into the cap-uncap PR.

**Falsifier:** traced wall-clock showing snapshot progress RMW dominating the same cycles as the 101s comment; or progress already writing a sidecar file only.

### 1.4 Raising the number ≠ full-active — **MODIFY**

**Keep:** with `SCORE_SNAPSHOT_MAX_SUBNETS=40` in `fly.toml`, worker calls `_cap_subnets_for_scoring(..., limit=cap)` only when `cap > 0` and `len(subnets) > cap` (`write_full_universe_snapshot`; `score_snapshots.py` ~333–337). Call chain: worker `score_snapshots.py` → `server._cap_subnets_for_scoring` → `internal/subnets/scoring_cap.cap_subnets_for_scoring`. Fresh snapshot rank-then-slice (`scoring_cap.py` ~102–107) is the Priority #4 feedback loop. Heuristic fallback excludes mega `rank ≤ 10`, prefers mid 11–75. Starvation at this pin: `rank_subnets_by_snapshot` keys missing netuids as **`-1.0`** (`scores.get(netuid, -1.0)`; `score_snapshots.py` ~221), not absence (Ditto Sept 21 theme). That is **D**, not a count bump.

**MODIFY:** `cap_subnets_for_scoring` selector is **skipped** when `len(subnets) <= cap` (return the list as-is; `scoring_cap.py` ~99–100). Writer skips `_cap_subnets_for_scoring` when resolved `cap == 0` **or** `len(subnets) <= cap` (runs only under `cap > 0 and subnets and len(subnets) > cap`). Explicit `SCORE_SNAPSHOT_MAX_SUBNETS=0` resolves to zero; **unset/empty** does not — worker `_snapshot_subnet_cap` falls back to `TOP_SCORING_UNIVERSE` (default **40**) (`score_snapshots.py:40-55`; see [#1354](https://github.com/cryptoreporthub/subnet-dashboard/pull/1354) @ `dd195788`). “Must bypass the selector” is one sufficient path, not the only one. Uncap on background is: membership list **and** resolved `cap == 0` or `cap >= len(membership)` **and** no `-1.0` fill for missing IDs **and** no heuristic mega-drop on that path.

**Hygiene (not §1.4 blocker):** module import `SCORE_SNAPSHOT_MAX_SUBNETS = int(os.environ.get(...))` (`score_snapshots.py:36`) raises on explicit empty string before `_snapshot_subnet_cap()` can treat empty as unset; Fly sets `"40"` so prod does not hit this. Phase 1 may add a guard; F04 cross-process `soul_map` stale-write remains a separate code-level risk — not §1.4 live incident.

Raising `TOP_SCORING_UNIVERSE` alone remains a trap (`min(24, TOP)` on scheduler/hot paths) — Ditto `1be445d1`. **ACCEPT** that constant-only uncap is rejected.

**Falsifier:** snapshot job already scores tradable membership without `cap_subnets_for_scoring` and without `-1.0` ranks.

### 1.5 Scheduler effective cap 20 + A/B — **ACCEPT**

Defaults: `PICK_SCHEDULER_UNIVERSE_CAP=24`, `server.TOP_SCORING_UNIVERSE=20`, `cap = min(...)`. A/B recorded on that list. Env UNKNOWN.

**Falsifier:** Fly web/worker `TOP_SCORING_UNIVERSE` / `PICK_SCHEDULER_UNIVERSE_CAP` process values ≠ those defaults (allowlisted probe).

### 1.6 90s tick / 129 risky — **MODIFY** (Composer PARTIAL)

**Keep:** `DAILY_PICK_TICK_TIMEOUT_SECONDS` default 90; timeout → `scheduler_hold` when today not ready. Do **not** score full-active inside that tick (Ditto + handoff: expand snapshot, keep tick as safety).

**Drop as code fact:** “129” is not a constant. Snapshot write budget is 480s Fly / 600s code default — different clock. Risk is **plausible**, not measured at this pin.

**Falsifier:** measured per-netuid `score_subnet_for_day` under shared load showing 90s can cover membership; or pick tick already snapshot-read-only.

### 1.7 Hidden 75 / 200 — **MODIFY** (Composer PARTIAL)

| Claim | Status at `dd195788` |
|-------|----------------------|
| `SCORING_CAP_MID_RANK_MAX` default 75 | CONFIRMED (`scoring_cap.py`, `fly.toml`) |
| `MAX_NETUIDS=200` chain + universe | CONFIRMED (envelope, not scoring policy) |
| Emergency registry “netuids 0–74” | **Docstring only**; `emergency_registry` uses `_emergency_rows()` with **no** `range(75)` |
| Live cache “clipped to ~75” | Comment + 75-subnet **batch deadline** language; no literal 75-row cap in `live_subnets.py` |

**Falsifier:** committed registry is exactly 0–74 and live cache truncates to 75 rows in code.

### 1.8 Tiny `REGISTRY_ONLY` input / denominator — **MODIFY** (Composer PARTIAL)

**Keep:** worker default `SCORE_SNAPSHOT_REGISTRY_ONLY` on; hydrate then `tradable_subnets`; else `_STATIC_SUBNETS` **3** rows. `count` is loaded/tradable length, not `subnet_universe` cardinality.

**MODIFY:** “denominator **must** be the universe snapshot” is the **design** (handoff Priority #2 + Claude honest coverage), not current behavior. Authoritative membership is still **blocked**: `summarize_subnets` / `is_active` is **provider `status=active` on `/api/subnets` rows**, which the handoff already says is not chain proof. Reusing that helper without a pinned chain/universe receipt **re-labels** the same definition problem.

**Falsifier:** snapshot `expected` taken from `UniverseSnapshot` netuids with explicit `emergency_registry` → `complete=false`; chain receipt attached.

### Claude “did not open” — **ACCEPT** Composer contradiction check

No refute from `scoring_cap.py` / `tradable.py` / `score_cache.py`. `/api/daily-pick/weighed` exists and uses server `_cap_subnets_for_scoring` (Composer extra). Claude’s truncation before that route is **not** a finding of absence.

---

## 2. Taxonomy D→A→B→C — **MODIFY** (order **ACCEPT**)

**ACCEPT** stop-at-first-yes **D then A then B then C**. D-first matches handoff Priority #3 and Ditto: honesty before uncap. C-preserve for math clamps, UI pages, retention, provider rates, load-shed — **ACCEPT**; do not delete the 2,119-row register.

**MODIFY mappings (this is the design correction):**

| Claude example under | Grok class | Why |
|----------------------|------------|-----|
| `count=len(rows)`, except-pass, `ok: True` on skip, silent cap, hour copied from day, `-1.0` missing ranks | **D** | Falsely green / silent drop |
| Snapshot **count** cap on background (`SCORE_SNAPSHOT_MAX_SUBNETS` when it truncates membership) | **A after Phase 1 RSS**, still **B** until coverage exists | Safety role today is VM budget; uncap only after measured snapshot job |
| Rank selector **on snapshot producer** | **A** once D coverage exists; until then it is a **workload governor** | Priority #4: must not use prior snapshot to decide **eligibility**; ranking for **display** can stay |
| `PICK_SCHEDULER_UNIVERSE_CAP` / `min(24, TOP)` | **B**, not A | 90s tick safety. Claude’s own P0 split says pick reads snapshot and rescores top-K. Uncapping this first reintroduces sync scoring (Ditto H1 trap) |
| Request-path `TOP_SCORING_UNIVERSE` / hot-path `min(24, TOP)` | **B** (`HOT_PATH_SCORE_BUDGET`) | Latency budget, not universe |
| Write/tick timeouts, refresh, `MAX_NETUIDS` | **B** | Keep; alert near envelope — **ACCEPT** 80% `MAX_NETUIDS` as ops, not scoring uncap |
| Conviction mins, `Math.min(100)`, message-intel | **C** | Handoff Priority #5; MC #1353 |

Orthogonal `runtime_verified` + `path` (background / request / UI) — **ACCEPT**.

Pre-classify whole register by script — **ACCEPT as method**, **REJECT as current artifact**: Claude did not classify “352 P0 caps”; MC 88 vs Replit 42 predicate gap is **open**; CSV @ `9535c3c2`. Re-scan at implementation SHA, unique `(path,line)`, do not sum `kinds`.

Count caution 700/565/246 vs 744/590 — **ACCEPT** Claude’s caution; do not use either pair as live P0.

**Falsifier for D→A order:** production already emits `complete`/`capped_out` and never `ok` on skip — then A on snapshot cap can start without a telemetry phase. **Falsifier for moving scheduler cap to A:** pick tick already snapshot-only with no `score_universe` on the 90s path.

---

## 3. P0 universe unification — **MODIFY**

**ACCEPT (core, handoff Priority #1):**
- Authority is a **membership resolver**, not a magic integer. Do not replace 40 with 128/129/64 as policy.
- Split `TOP_SCORING_UNIVERSE` into **scoring set** (background = membership, no count cap at end state), **request-path latency budget**, **pick candidate pool** (snapshot-fed top-K). Departing from “one number everywhere” is **correct**.
- One module / one read per symbol + CI against duplicate defaults.
- Boot log of **allowlisted** effective values per process (closes UNKNOWN table without `printenv`).
- Honest coverage block: `expected`, `attempted`, `succeeded`, `failed[]`, `skipped_invalid`, `capped_out`, `universe_status`, `source`, `selection_policy`; `complete` iff succeeded set **equals** expected; `ok` false on skipped publish; liveness success only on `complete`; partial publishes with the block; consumers gate on it.
- Sequential scoring; cancel token; replace per-20 soul_map progress with a sidecar; **do not raise 480s**; hour scoring stays **off** as default until measured.
- Chunk + yield under `MAX_IN_FLIGHT_REQUESTS` — **ACCEPT** as tactic (`ponytail:` ceiling: cooperative yield, not a new universe size).

**MODIFY:**
1. **Phase 2 “pin 20, 24, 40 in `fly.toml` as no-op” cannot use one `TOP_SCORING_UNIVERSE`.** Today: server default **20**, engine/audit/snapshot-worker-fallback default **40**, scheduler **min(24, server 20)=20**, Fly snapshot cap **40**. Setting `TOP_SCORING_UNIVERSE=20` in `fly.toml` **changes** engine/audit. Setting `=40` **changes** web/scheduler. No-op unification = **split env names first**, each pinned to **current path-effective** default, CI that no file reintroduces a second default. That **is** Priority #1.
2. **`summarize_subnets` is not chain membership.** It counts `status=active` on display rows (`active_subnet_policy` string in `summary.py`). Handoff Priority #2: provider active ≠ chain; Root out of alpha scoring, not hidden from network display. Membership `expected` must come from `UniverseSnapshot` (or a later pinned chain source) with `emergency_registry`/`degraded` ⇒ `complete=false`.
3. **REJECT “129 small rows are trivial.”** Ditto: 128-in-1GB is not transferable to inline/`score_subnet_for_day` (soul_map deepcopy storms). Gate on Phase 1 VmRSS; do not pre-declare trivial.
4. Scoring set = membership **is end state of Phase 3**, not Phase 2. Phase 2 must not widen the snapshot cap.

**Falsifier:** allowlisted prod env already equalizes all four numbers to membership size **and** request paths only read snapshots — then split names are still hygiene, not a load change. **Falsifier for membership:** pinned chain/universe receipt whose active-non-root set is the scoring `expected`.

---

## 4. Rollout (3-phase) — **MODIFY** (shape **ACCEPT**)

**ACCEPT sequence (do not reorder):**  
Phase 1 telemetry / honesty, **no** universe change → Phase 2 config split **no-op** → Phase 3 stepped **background** expansion with handoff rollback triggers.

**Phase 1 scope (MC MODIFY — Replit + Ditto):** Telemetry and honesty only. **Move into Phase 1** (read-only where possible): denominator and **provenance** capture on each snapshot cycle (`expected` source, `universe_status`, membership receipt fields), and **fail-closed** reporting when membership is unknown, stale, `emergency_registry`, degraded, or clipped. **Do not** change scoring caps, membership **selection** policy, or hot-path budgets in Phase 1.

**ACCEPT Phase 1 exit:** injected scoring failure stays **partial**, never green, for **`PHASE1_CONSECUTIVE_PARTIAL_CYCLES`** consecutive cycles (default **3**, testable constant). Skipped-older publish → `ok: false` / `published: false`. Coverage capture must complete within **`PHASE1_COVERAGE_CAPTURE_MAX_SECONDS`** (named in the Phase 1 PR so the gate is exercisable in tests without prod mutation).

**ACCEPT Phase 2 exit:** allowlisted effective dump identical before/after **per split symbol**.

### Phase 1 acceptance criteria (Replit `6105598176` + Ditto `5482225410` — MC accepts all)

Phase 1 implementation PR (draft allowed; no prod deploy) must satisfy:

1. **Membership receipt:** verified, **fresh** membership provenance attached to each coverage block (pinned source + timestamp); not inferred from `len(rows)` alone.
2. **Root policy:** explicit in coverage (`root_in_scoring_set=false` or equivalent).
3. **`cap_reached=false`** and **`refresh_incomplete=false`** required for `complete=true` (when those fields apply to the membership source).
4. **Per-horizon ID equality:** `succeeded` netuid sets must **exactly equal** `expected` for each horizon claimed complete.
5. **Fail-closed:** unknown, stale, `emergency_registry`, degraded, or **clipped** membership ⇒ `complete=false` (never falsely green).
6. **Publish honesty:** skipped older stamp ⇒ `published=false` and cycle success must not treat it as a full publish.
7. **Hour copy label:** day-copied hour rows labeled **`copied_from_day`** (or hour scoring on).
8. **Counterexample (synthetic, source-level — not prod):** `_compute_membership` / `SnapshotBuilder` can emit **`status=ok`** with **`cap_reached=true`** when inputs exceed `MAX_NETUIDS` (e.g. `tests/test_subnet_universe.py` `test_t4_cap_at_max_netuids`: 250 candidates → 200 netuids). Use only to prove **`ok` ≠ complete**; prod must not treat clipped membership as full-active.
9. **Measured write duration (not prod mutation):**
   - **(a) Measurement AC (required — Replit ACCEPT):** each snapshot cycle must record **score-snapshot write wall time** (or equivalent stage timing) in the coverage/telemetry block. Phase 1 uses this to calibrate honesty gates; **does not** relax merge-soak stall-guard or P4b HOLD.
   - **(b) Historical Soak 5 interpretation (audit trail):** Deploy C snapshot-write / stall-guard narrative is supported by [`soak-5-snapshot-write-axiom-receipt-2026-10-11.md`](../evidence/soak-5-snapshot-write-axiom-receipt-2026-10-11.md) (**MC-verified Axiom export**; filed for MC/Joshua audit trail — **not** Replit-verified). Independent re-spot of Axiom remains optional. Receipt documents `write_timeout_480s`, stale ages, and guard lines at `12:37` / `12:46` / `12:50`; resolver first-success **`12:10:54.888Z`** is a **separate MC Axiom datum** (outside the receipt’s `12:11` window) — snapshot-write cost class, not resolver failure.

**F04 (persistence):** Cross-process **`soul_map` lost-update** remains **open** and **out of scope** for Phase 1 cap telemetry. [#1317](https://github.com/cryptoreporthub/subnet-dashboard/pull/1317) fixed **same-process** latest-state mutation only; snapshot progress RMW and resolver RMW still share the file across processes.

**MODIFY Phase 3:**
- **REJECT 40→64→full as a new policy constant.** User/handoff: do not replace 40 with another magic number. **64 may be a measured batch/soak rung**, recorded from Phase 1 cost, not a committed universe. Eligibility = membership; steps = **workload batches**, not `TOP=64`.
- Pick path **20→24→snapshot-fed pool** — **ACCEPT** the last arrow as the real uncap. Intermediate 24 only if still scoring on the tick (should not, once snapshot-fed). Do not grow the 90s tick to 129.
- Selection for **eligibility** must not depend on prior snapshot (Priority #4). Using snapshot scores to pick top-K **after** full-active `complete` is allowed.
- Memory/latency/overlap gates — **ACCEPT**; calibrate RSS from Phase 1, not a guessed MB.
- Human approval still required to merge/deploy/raise caps (handoff). Not on listener PR #1348.

**Falsifier for skipping Phase 1:** coverage block + `ok` semantics already on prod. **Falsifier for 64:** Phase 1 shows a stable batch size that happens to be 64 **as measured**, then it is a rung not a product constant.

---

## 5. CSV @ `9535c3c2` — **flag**

Do **not** treat as live at `dd195788`:
- 2,119 row inventory (historical discovery — keep)
- MC 88 vs independent 42 P0 predicate
- Claude “352 P0” / 700/565/246
- Any implementation allowlist derived only from that CSV

Before an implementation PR: re-scan **exact** source SHA (`dd195788` or then-main / then-`/version`), diff vs `9535c3c2`, keep old CSV as evidence. `#1348` is listener/watchdog; Composer did not claim cap-path identity beyond this pin — still **re-scan**, do not assume.

---

## 6. Handoff (this PR)

- Priority #3: `count=len(rows)` after `tradable_subnets()` (successful scores remain a different set) — applied in `cursor-cap-audit-handoff.md`.
- Priority #1 **24 vs 40 @ `dd195788`:** `server.py` default **20**; engine/audit modules default **40** when env unset. `PICK_SCHEDULER_UNIVERSE_CAP` **24** is an upper bound; `pick_scheduler` uses `min(24, server.TOP_SCORING_UNIVERSE)` → **20** on the default web import path. Engine paths that resolve TOP with default 40 may still use `min(24, 40)` → **24**. Handoff Priority #1 updated accordingly (not “scheduler always 24”).
- Priority #1 **unify intended coverage:** see **§1.4 / §3** — split env names (`HOT_PATH_SCORE_BUDGET`, snapshot cap, scheduler ceiling) instead of one `TOP_SCORING_UNIVERSE` in `fly.toml`.

---

## 7. What to implement later (not this PR)

1. **Phase 1 telemetry PR (draft):** coverage schema + `ok`/`complete`/`degraded` + provenance/denominator capture; must name **`PHASE1_CONSECUTIVE_PARTIAL_CYCLES`** (default 3) and **`PHASE1_COVERAGE_CAPTURE_MAX_SECONDS`** for testable exit gates; satisfy §4 AC above. No cap/membership/budget behavior change.  
2. Split config symbols + CI duplicate-default test + boot allowlist log (Phase 2).  
3. Snapshot producer: membership `expected`, no rank eligibility, no `-1.0` ghost ranks, sidecar progress (Phase 3 after gates).  
4. Request/pick: read snapshot only.

**Do not:** raise `DAILY_PICK_TICK_TIMEOUT_SECONDS` or `SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS`; uncap scheduler before snapshot-fed; classify C-rows as scoring caps from the 9535 CSV.

---

## Top MODIFY items (index)

1. Phase 2 cannot no-op via a single `TOP_SCORING_UNIVERSE` in `fly.toml` — split names to current 20 / min(24,20) / 40 / 40.  
2. `PICK_SCHEDULER_UNIVERSE_CAP` is **B** (tick safety), not **A**.  
3. Finding 3 PARTIAL: scheduler soul_map progress ≠ resolver 101s comment.  
4. Finding 7 PARTIAL: 0–74 / live-75 are comments, not code caps.  
5. Phase 3: no magic **64**; batches from measurement.  
6. `summarize_subnets` ≠ chain membership.  
7. Reject “129 rows trivial.”  
8. Selector skip when `len≤cap`; missing ranks `-1.0` is D.  
9. Handoff `len(inputs)` wording.  
10. CSV pin: no live classification without re-scan.
