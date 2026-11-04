# Plan: Daily pick at ~12:05 PM America/Phoenix (19:05 UTC, no-migration redesign)

**Status:** Approved for implementation (PR #1561). **Supersedes** bulk migration / WAL / audit-rename / legacy relabel (removed per Joshua + Replit redesign).

**Verification:** Code refs below from branch `cursor/daily-pick-morning-plan-3740` @ **`89d891c6`** (same tree as `main` for cited paths).

**Goal:** Move authoritative daily pick generation to **19:05 UTC** (~12:05 PM America/Phoenix) with **19:00 UTC pick-day rollover**, without rewriting history on disk.

---

## 1. Problem (verified)

| Issue | Evidence |
|-------|----------|
| Slot defaults **00:15 UTC** (pre-change) | `pick_day.py` — **`DAILY_PICK_SLOT_UTC_*` default 19:05**, rollover **19:00** |
| “Today” = UTC calendar midnight | `internal/council/daily_pick_engine.py:140-141` — `_today_str()` → `datetime.now(timezone.utc).date().isoformat()` |
| Cold boot arms **45s** create tick | `pick_scheduler.py:273` — `schedule_in_seconds(DAILY_JOB_ID, self._tick, 45)` before `already running` return (`:274-275`) |
| Selection time **restamped** each attempt | `daily_pick_engine.py:321`, `:364` — `"build_started_at": started` on every persist path |
| Side paths can create early | `get_or_create_today_pick` callers (§4); scheduler `:328+` tick |

**19:00–19:05 gap:** After rollover, `pick_day_str()` is **D** but no **D** row until 19:05 — readers must not show HOLD-only gap (§3).

---

## 2. Design principles (no migration)

1. **Legacy rows and `data/pick_audits/{date}.json` stay untouched** — no relabel, rename, WAL, or marker files.
2. **New writes** use **`pick_id: "v2:<pick_day>"`**, **`schema_version: 2`**, **`pick_day`** (ISO date from `pick_day_str()`), plus existing display fields (`date` may mirror `pick_day` for compat).
3. **`selection_recorded_at_utc`** set **once** on first **published** persist for that `pick_id` (`is_published_daily_pick_row` — not on HOLD-only attempts); **never** updated on retry/regen.
4. **One reader rule everywhere** (§3).
5. **Generation-token write fence** for concurrent resolver/pick RMW (§5) — **never block process boot**; on hard timeout: revoke token, keep serving last published pick, disable new scheduler ticks, expose unhealthy — ops recovers.

---

## 3. Shared pick-day + reader rule

**Module:** `internal/council/pick_day.py` (new).

| Constant | Default | Role |
|----------|---------|------|
| `PICK_DAY_ROLLOVER_UTC_HOUR` / `MINUTE` | `19` / `0` | Pick-day string advances |
| `DAILY_PICK_SLOT_UTC_HOUR` / `MINUTE` | `19` / `5` (code defaults; env optional) | Scheduler slot (existing env names) |

**Rollover (normative):** let `now_utc = now.astimezone(timezone.utc)`, `t = now_utc.time()`. If `t < time(19, 0)` (rollover constants env-overridable), **`pick_day_str(now) = (now_utc.date() - 1 day).isoformat()`**; else **`pick_day_str(now) = now_utc.date().isoformat()`**.

**Pick-day start:** **`pick_day_start_utc(pick_day)`** = **`datetime.combine(date.fromisoformat(pick_day), time(19, 0), tzinfo=timezone.utc)`** (rollover hour/minute from env).

**Slot open instant (normative, one formula):** for **`pick_day = pick_day_str(now)`**,

```text
slot_open_utc(pick_day) = datetime.combine(
    date.fromisoformat(pick_day),
    time(DAILY_PICK_SLOT_UTC_HOUR, DAILY_PICK_SLOT_UTC_MINUTE),
    tzinfo=timezone.utc,
)
daily_pick_creation_open(now)  ⇔  now_utc >= slot_open_utc(pick_day)
```

Default env → **`slot_open_utc = pick_day calendar date at 19:05:00 UTC`**. **`force=True` does not bypass.** At **`19:00:00 ≤ now < slot_open`**, pick day has already rolled but creation is **closed** (reader uses §3 prior published).

**Boundary tests (§7):** freeze **`2026-11-04 19:04:59 UTC`** → `pick_day_str` **`2026-11-04`**, **`daily_pick_creation_open` false**; **`19:05:00 UTC`** → **true**; **`19:00:00 UTC`** → pick day **`2026-11-04`**, creation **false**; **`18:59:59 UTC`** → pick day **`2026-11-03`**, creation **true** (slot for **`2026-11-03`** already passed).

### Published row

**`is_published_daily_pick_row(rec)`:** not `scheduler_hold`; `action` in `LONG`/`BUY`; `pick` is a dict.

### One shared reader rule (normative)

For current **`pick_day = pick_day_str()`**:

1. Prefer **published v2** row with **`pick_id == f"v2:{pick_day}"`** (or `schema_version >= 2` and matching `pick_day`).
2. Else **latest published** row with **`pick_day` or legacy `date` strictly before `pick_day`** (prior pick day only) — **never** HOLD / `scheduler_hold`.
3. **Legacy same-day exclusion:** if **any** published v2 row exists for **`pick_day`**, **or** after cutover deploy (v2 writes enabled), **never** present a legacy v1 row whose **`date == pick_day`** as the current pick — even if it is the newest legacy row for that calendar key. Legacy **`date == pick_day`** rows remain on disk but are **historical**, not hero.
4. Meta **`prior_pick_day: true`** when displayed row’s effective pick day ≠ `pick_day`.

**Pre/post cutover:** legacy v1 rows and v2 rows **coexist**; reader never requires migration. **19:00:30 UTC** test: show prior published row, not empty hero.

**Migration gate removed:** hero uses **`last_good_published_pick`** / rule above always — no 503 for missing marker.

---

## 4. Writers

- **`_upsert_today` → upsert by `pick_id`** (v2) under existing **`daily_picks.json` lock** (`daily_pick_engine.py:72-88`, `:96-137`) — atomic RMW; legacy rows keyed only by `date` remain as-is.
- **`get_or_create_today_pick`:** if not **`daily_pick_creation_open()`**, **no** `select_daily_pick` / `_save` — **`force=True` included**. Read paths use §3 only.
- **Scheduler:** when creation closed, schedule **`_seconds_until_daily_slot()`** (`pick_scheduler.py:69-73`), **not** 45s early create (`:273` target change).
- **Audits (new only):** `pick_selection_audit` writes **`data/pick_audits/by_pick_id/v2_<pick_day>.json`** (or embed `pick_id` in payload); **legacy date-keyed audit files unchanged** and still valid for old rows.
- **Post-marker legacy-key refusal removed** — replaced by v2 `pick_id` upsert; old code paths must not overwrite v2 row for same calendar day without matching `pick_id`.

---

## 5. Generation-token write fence (resolver + pick)

**Pattern (existing):** `PredictionResolverScheduler` uses **`_cycle_generation`** / **`_persist_owner_gen`** (`internal/council/resolver_scheduler.py:434-436`, `:778-790`, owner checks `:1014`, `:1126`, `:1156`).

**Single lock (normative):** one process-wide **`threading.Lock`** — **`daily_pick_write_token_lock`** — shared by **token issue**, **revocation**, **validate**, and **each guarded local disk commit** (§5.1). **Lock scope:** **never** across a whole resolver job, network I/O, RPC, or grading compute — only **validate-token + bounded local atomic commit** at listed write sites. Under the lock: **only bounded local atomic commit** (temp → fsync → replace, or existing **`_save_json` / `write_soul_map` / heal** helpers that already atomic-rename) — not unbounded or remote I/O.

**Token issue / revocation:** same lock. **Issue** and **revoke** (`resolver_scheduler.py:778-790`) perform a **brief in-memory swap** (generation / revoked flag / `_abandon_inflight_cycle`) — no network. **Revocation** may block behind **at most one in-flight bounded local commit** already holding the lock; it must **not** wait on resolver work **outside** the lock (hung compute). **After `revoke_daily_pick_write_token()` returns**, no guarded site may still publish a **stale** post-revoke commit (§5.1 race rule).

**Normative:**

- **Bounded wait** (default **3600s**, env) for in-flight resolver cycle **without holding `daily_pick_write_token_lock`** before pick slot write.
- **On timeout:** call **`revoke_daily_pick_write_token()`**; **do not block boot**; **disable** new daily pick schedule until token re-armed; **continue serving** §3; `/health` **`daily_pick_write_fence_timeout: true`**.

**Guarded sites:** prepare payload **outside** lock; **under lock:** validate token → **bounded local atomic commit** → release (§5.1). Stale token → **no commit** (return before write).

| Write site | Location @ `89d891c6` | Pattern (validate-token + bounded atomic commit under lock) |
|------------|------------------------|-------------------------------------------------------------|
| Pick JSON RMW | `daily_pick_engine.py:96-137` `_save` / upsert | **Outside:** build row. **Inside lock:** `allowed()` → fcntl + atomic pick persist (same bounded RMW as today) |
| Predictions persist | `resolver.py:1323`, `:1383`, `:1523`, `:1673` | **Outside:** serialize. **Inside lock:** `allowed()` → `_save_json` (atomic) |
| Cycle summary + soul_map RMW | `resolver_scheduler.py:1154-1158`, `:1219` | **Outside:** summary / map payload. **Inside lock:** `allowed()` → `write_soul_map` |
| Partial / stage persists | `resolver_scheduler.py:1010-1021` | **Outside:** summary. **Inside lock:** `allowed()` → `_persist_cycle_summary` |
| Cycle `finally` persist | `resolver_scheduler.py:1124-1138` | same |
| Skipped / timeout summary | `resolver_scheduler.py:605`, `:823`, `:935` | same |
| Lifecycle state on soul_map | `resolver_scheduler.py:740-752` | same |
| Ledger heal | `resolver_scheduler.py:1030-1034` | **Outside:** inputs. **Inside lock:** `allowed()` → `heal_daily_pick_ledger` |
| Grading | `resolver_scheduler.py:1074-1075`, `:1093-1100` | **Outside lock:** grading + resolver RPC. **Each persist site:** validate + bounded atomic commit under lock |
| Auto-retrain | `resolver_scheduler.py:1112-1118` | **Outside lock:** retrain. Disk-touching effects: validate + bounded atomic commit under lock |

- **Never** unbounded wait **for the lock** on hung job work **outside** the lock; revocation waits **at most one bounded local commit**, not whole-cycle compute.

**Process model:** Inline worker on same VM — `scripts/fly_web_entrypoint.sh:3-5`, worker `:92-94`; fence runs in **worker** where resolver + pick schedulers live.

### 5.1 Validate-token + bounded local atomic commit (same lock as revocation)

**Middle ground (supersedes `653da892` release-before-write):** releasing the lock **before** disk write allowed check → revoke → write **race** (stale commit after revoke). Normative pattern at every guarded site:

1. **Outside lock:** prepare payload (serialize JSON, build pick row, read inputs — no token check).
2. **`with daily_pick_write_token_lock:`** **`if not daily_pick_write_token_allowed(): return`** (no commit).
3. **Still inside lock:** run **bounded local atomic commit** only — temp + fsync + replace, or **`_save_json` / `write_soul_map` / `heal_daily_pick_ledger` / pick fcntl RMW** as implemented today (must complete in bounded local time; not network).
4. **Release lock.**

**Revocation interaction:** **`revoke_daily_pick_write_token()`** uses the **same** lock. Revocation may wait for **one** in-progress bounded local commit to finish; it must **not** wait on threads stuck in compute **outside** the lock. **Race rule:** concurrent **revoke during commit** — disk ends **fully committed before revoke visible** OR commit **aborted/rejected** (no token); **never** a visible stale write **after** revoke completes.

**Forbidden:** lock held across **`run_cycle`**, grading, network/RPC, or whole jobs.

**Representative sites:** **`resolver_scheduler` soul-map summary** (captured cycle `write_generation`), **`daily_pick_engine._save`**, **`ledger_heal` heal commit** (resolver cycle gen when in-tick).

**Exception (intentional):** **`resolver._save_json`** for **`predictions.json`** — `predictions_store` file lock only; not daily-pick token (grading writes are not pick JSON RMW).

**Tests (§7):** **`tests/test_daily_pick_write_token.py`** — hung-outside-lock; **revoke-during-commit race**; post-revoke sites rejected @ listed lines.

---

## 6. Call sites → `pick_day_str()` + §3 reader

| Area | Location | Action |
|------|----------|--------|
| Engine | `daily_pick_engine.py:140-155`, `:242`, `:312`, `:355` | `pick_day_str`; v2 fields on write |
| Scheduler | `pick_scheduler.py` (imports slot from `pick_day.py`) | Slot defaults **19:05**; gate cold 45s |
| Server shed | `server.py:3312` | `pick_day_str` |
| Server meta | `server.py:3212`, `3224`, `3321` (approx) | `pick_day_str` in API payloads |
| Ledger / health | `ledger_heal.py:32`, `loop_health.py:67`, `readiness.py:99` | `pick_day_str` |
| Cockpit SSE | `picks_snapshot.py:127` | `pick_day_str` + §3 |
| Conviction | `conviction_alerts/evaluate.py:55-67` | `pick_day_str` + §3 |
| Letter | `brain_letter.py:137`, `189`, `288`, `411` | `pick_day_str` + §3; `:232` wall-clock |
| Audits | `pick_selection_audit.py:43`, `:300`, `:318`, `:346` | New audits by **`pick_id`**; defaults `pick_day_str` |
| Outcome | `outcome_snapshot.py:49`, `:67` | Read audit by **`pick_id`** with legacy path fallback |
| Ops evidence | `ops/evidence.py:65` | `pick_id` / pick_day path for v2 |
| Selector | `selector.py:178` | `pick_day_str` on daily artifacts |
| Preview | `k3_hold.py:37`, `tribunal_hero.py:148`, `:840` | §3 read path |
| SimiVision | `caution_cells.py:26`, `:56`, `:187-195` | §3 via shared helper; `pick_day_str` for day keys |
| SimiVision chat | **`chat_service.py:387-395`** — loads **`daily_picks.json[0]`** today | **Replace with §3 reader** (not first list element); `graded_context.py:115+`, `weighing_room.py:193+` consume injected pick |
| Scripts | `nightly_pick_audit.sh:21` | After slot; target **`pick_id`** |
| Read-only | `story_path`, `pick_explain`, `panel_summaries_lite`, `/api/daily-pick` hydrate | §3 only; no create before slot |
| Wall-clock (no change) | `message_intel/rollup.py:520`, `2728`, `2735`; `brain_letter.py:232` | Document only |

**Nightly audit:** **≥ 19:10 UTC**; gate on `daily_pick_creation_open()`; no `get_or_create` before slot.

---

## 7. Minimum tests (implement in follow-on PR)

| Test | Assert |
|------|--------|
| `test_pick_day.py` | Rollover **18:59:59 / 19:00:00**; gate **19:04:59 / 19:05:00** on same calendar day; **`18:59:59` open** for prior pick day (§3 formula) |
| Steady 19:00:30 | §3 shows prior published, not HOLD gap |
| v2 row | `selection_recorded_at_utc` set on first **published** persist only; unchanged after HOLD retry |
| `force=True` before slot | **No** persist (`daily_pick_creation_open` enforced) |
| Legacy same-day | v2 published for **D** exists → reader must not surface legacy **`date==D`** as current |
| Legacy coexistence | Disk has legacy `date=D` + no v2; after 19:05 v2 created; reader prefers v2 when published |
| Upsert | Two writers same `pick_id` → one row (lock) |
| Fence timeout | Revocation acquires lock **briefly** while resolver thread **hung outside lock** (simulate slow compute without lock); schedule disabled; **later** validate-then-commit at write site **rejected** (stale token) |
| Cold boot | Creation closed → next slot, not 45s persist (`pick_scheduler`) |
| Read-only paths | No `select_daily_pick` before slot (homepage / story_path pattern) |
| Contract | `tests/test_endpoint_contract.py` unchanged |
| Token lock scope | **`tests/test_daily_pick_write_token.py`** — §5.1 @ **`resolver.py:1323`**, **`resolver_scheduler.py:1219`**, **`1030-1034`**; **hung outside lock** does not block revocation; post-revoke commit **rejected** |
| Revoke during commit race | Same module — interleave **revoke** with bounded atomic commit: outcome **committed-before-revoke OR rejected**, **never** stale visible state **after** revoke returns |

**Standing gate:** do not bump `DAILY_PICK_TICK_TIMEOUT_SECONDS` or unmute `LOOP_STALL_GUARD_KILL`.

---

## 8. Deploy & risks

- **Defaults:** code `DAILY_PICK_SLOT_UTC_HOUR=19`, `DAILY_PICK_SLOT_UTC_MINUTE=5`; rollover **19:00** (`pick_day.py`; scheduler imports — Fly env optional).
- **1 GB VM:** staging peak RSS for full morning tick (§8 legacy note in DEPLOY / scoring-caps — measure before human deploy).
- **Risk:** dual schema on disk until old rows age out — mitigated by §3 reader; **no** one-shot rewrite.

---

## 9. Implementation sequence

1. `pick_day.py` + v2 row shape + selection-once + upsert-by-`pick_id`.
2. Reader helper + migrate call sites (§6).
3. Scheduler gate + fence token integration.
4. Audit-by-`pick_id` for new runs only.
5. Tests §7; human-gated Fly deploy.

**Removed from prior plan:** §6 migration map, audit renames, WAL/progress/marker, legacy relabel windows, resolver migration boot block, collision closure, `pick_day_selection_instant_utc` backfill.

---

## Known limit (Joshua accepted)

If local disk stalls during **fsync** inside a guarded **validate-token + bounded local atomic commit**, the commit holds **`daily_pick_write_token_lock`** until the kernel returns — **revocation waits** behind that commit (at most one bounded local write). A **frozen disk** breaks the site regardless; no timeout logic will forcibly release the lock mid-commit.

**Mitigation (observability only):** log guarded commit duration at info/warning; expose **`/api/health`** (and JSON detail on **`/health`** when requested) **`daily_pick_commit_slow: true`** when any guarded commit exceeds **5s**. **No automatic timeout or lock break.**

### Process model (threading.Lock fence)

**Prod layout (`fly.toml`):** web `RUN_MODE=web`, **`BACKGROUND_ON_WEB=off`**, inline worker sibling **`RUN_MODE=worker`** (`scripts/fly_web_entrypoint.sh` **:92–:94** `setsid … internal.worker`; web **:148** `exec python scripts/run_web_with_guard.py`).

**Guarded writes** (token + resolver/pick RMW) run from **`background_boot`** schedulers — **worker process only** in prod (web skips background boot). HTTP read paths use **`get_current_daily_pick` / `load_current_daily_pick`** only; **`server.py` has no `get_or_create_today_pick()` call sites**.

**Caveat:** `threading.Lock` is **process-local**. If **`BACKGROUND_ON_WEB=on`**, the web process would also start resolver/pick schedulers with a **separate** token — not prod config today. **`ledger_heal._downgrade_today_to_hold`** still writes pick JSON without the token (worker boot/recover path only).
