# Plan: Daily pick at ~6:05 AM America/Phoenix (no-migration redesign)

**Status:** Plan only (PR #1561 draft). **Supersedes** bulk migration / WAL / audit-rename / legacy relabel (removed per Joshua + Replit redesign).

**Verification:** Code refs below from branch `cursor/daily-pick-morning-plan-3740` @ **`89d891c6`** (same tree as `main` for cited paths).

**Goal:** Move authoritative daily pick generation to **13:05 UTC** (~06:05 America/Phoenix) with **13:00 UTC pick-day rollover**, without rewriting history on disk.

---

## 1. Problem (verified)

| Issue | Evidence |
|-------|----------|
| Slot defaults **00:15 UTC** | `internal/council/pick_scheduler.py:32-33` — `DAILY_PICK_SLOT_UTC_HOUR` default `"0"`, minute `"15"` |
| “Today” = UTC calendar midnight | `internal/council/daily_pick_engine.py:140-141` — `_today_str()` → `datetime.now(timezone.utc).date().isoformat()` |
| Cold boot arms **45s** create tick | `pick_scheduler.py:273` — `schedule_in_seconds(DAILY_JOB_ID, self._tick, 45)` before `already running` return (`:274-275`) |
| Selection time **restamped** each attempt | `daily_pick_engine.py:321`, `:364` — `"build_started_at": started` on every persist path |
| Side paths can create early | `get_or_create_today_pick` callers (§4); scheduler `:328+` tick |

**13:00–13:05 gap:** After rollover, `pick_day_str()` is **D** but no **D** row until 13:05 — readers must not show HOLD-only gap (§3).

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
| `PICK_DAY_ROLLOVER_UTC_HOUR` / `MINUTE` | `13` / `0` | Pick-day string advances |
| `DAILY_PICK_SLOT_UTC_HOUR` / `MINUTE` | `13` / `5` (env at deploy) | Scheduler slot (existing env names) |

**Rollover (normative):** let `now_utc = now.astimezone(timezone.utc)`, `t = now_utc.time()`. If `t < time(13, 0)` (rollover constants env-overridable), **`pick_day_str(now) = (now_utc.date() - 1 day).isoformat()`**; else **`pick_day_str(now) = now_utc.date().isoformat()`**.

**Pick-day start:** **`pick_day_start_utc(pick_day)`** = **`datetime.combine(date.fromisoformat(pick_day), time(13, 0), tzinfo=timezone.utc)`** (rollover hour/minute from env).

**Slot open instant (normative, one formula):** for **`pick_day = pick_day_str(now)`**,

```text
slot_open_utc(pick_day) = datetime.combine(
    date.fromisoformat(pick_day),
    time(DAILY_PICK_SLOT_UTC_HOUR, DAILY_PICK_SLOT_UTC_MINUTE),
    tzinfo=timezone.utc,
)
daily_pick_creation_open(now)  ⇔  now_utc >= slot_open_utc(pick_day)
```

Default env → **`slot_open_utc = pick_day calendar date at 13:05:00 UTC`**. **`force=True` does not bypass.** At **`13:00:00 ≤ now < slot_open`**, pick day has already rolled but creation is **closed** (reader uses §3 prior published).

**Boundary tests (§7):** freeze **`2026-11-04 13:04:59 UTC`** → `pick_day_str` **`2026-11-04`**, **`daily_pick_creation_open` false**; **`13:05:00 UTC`** → **true**; **`13:00:00 UTC`** → pick day **`2026-11-04`**, creation **false**; **`12:59:59 UTC`** → pick day **`2026-11-03`**, creation **true** (slot for **`2026-11-03`** already passed).

### Published row

**`is_published_daily_pick_row(rec)`:** not `scheduler_hold`; `action` in `LONG`/`BUY`; `pick` is a dict.

### One shared reader rule (normative)

For current **`pick_day = pick_day_str()`**:

1. Prefer **published v2** row with **`pick_id == f"v2:{pick_day}"`** (or `schema_version >= 2` and matching `pick_day`).
2. Else **latest published** row with **`pick_day` or legacy `date` strictly before `pick_day`** (prior pick day only) — **never** HOLD / `scheduler_hold`.
3. **Legacy same-day exclusion:** if **any** published v2 row exists for **`pick_day`**, **or** after cutover deploy (v2 writes enabled), **never** present a legacy v1 row whose **`date == pick_day`** as the current pick — even if it is the newest legacy row for that calendar key. Legacy **`date == pick_day`** rows remain on disk but are **historical**, not hero.
4. Meta **`prior_pick_day: true`** when displayed row’s effective pick day ≠ `pick_day`.

**Pre/post cutover:** legacy v1 rows and v2 rows **coexist**; reader never requires migration. **13:00:30 UTC** test: show prior published row, not empty hero.

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

**Normative:**

- Under **same lock as pick JSON RMW** (`daily_picks.json.lock`), pick persist checks **active write token** (shared with resolver persist gate — impl names **`daily_pick_write_token`**).
- **Bounded wait** (default **3600s**, env) for in-flight resolver cycle before pick slot write.
- **On timeout:** **revoke token** (mirror `_abandon_inflight_cycle`, `resolver_scheduler.py:778-790`); **do not block boot**; **disable** new daily pick schedule until token re-armed; **continue serving** §3; `/health` **`daily_pick_write_fence_timeout: true`**.

**After revocation, every resolver-owned disk write must no-op** until a new cycle owns the token — wrap **`daily_pick_write_token_allowed()`** (same check as pick RMW):

| Write site | Location @ `89d891c6` |
|------------|------------------------|
| Predictions persist | `internal/council/resolver.py:1323`, `:1383`, `:1523`, `:1673` — `_save_json(PREDICTIONS_PATH, …)` |
| Cycle summary + soul_map RMW | `internal/council/resolver_scheduler.py:1141-1158` → `:1219` `write_soul_map(...)` in `_persist_cycle_summary_locked` |
| Partial / stage persists | `resolver_scheduler.py:1010-1021` `persist_partial` → `_persist_cycle_summary` |
| Cycle `finally` persist | `resolver_scheduler.py:1124-1138` |
| Skipped / timeout summary | `resolver_scheduler.py:605`, `:823`, `:935` — `_persist_cycle_summary(...)` |
| Lifecycle state on soul_map | `resolver_scheduler.py:740-752` `_persist_lifecycle_state` → `write_soul_map` |
| Ledger heal (mutates daily pick) | `resolver_scheduler.py:1030-1034` `heal_daily_pick_ledger(dry_run=False)` |
| Grading entrypoints | `resolver_scheduler.py:1074-1075` `resolve_due_predictions`; `:1093-1100` `expire_stale_predictions` (must not reach `_save_json` when token revoked) |
| Auto-retrain side effects | `resolver_scheduler.py:1112-1118` `maybe_trigger_auto_retrain` (no disk write that touches picks/predictions/soul_map when revoked) |

- **Never** unbounded wait.

**Process model:** Inline worker on same VM — `scripts/fly_web_entrypoint.sh:3-5`, worker `:92-94`; fence runs in **worker** where resolver + pick schedulers live.

---

## 6. Call sites → `pick_day_str()` + §3 reader

| Area | Location | Action |
|------|----------|--------|
| Engine | `daily_pick_engine.py:140-155`, `:242`, `:312`, `:355` | `pick_day_str`; v2 fields on write |
| Scheduler | `pick_scheduler.py:32-33`, `:273`, `:69-73` | Slot env **13:05** deploy; gate cold 45s |
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

**Nightly audit:** **≥ 13:10 UTC**; gate on `daily_pick_creation_open()`; no `get_or_create` before slot.

---

## 7. Minimum tests (implement in follow-on PR)

| Test | Assert |
|------|--------|
| `test_pick_day.py` | Rollover 12:59 vs 13:00; gate 13:04 vs 13:05 |
| Steady 13:00:30 | §3 shows prior published, not HOLD gap |
| v2 row | `selection_recorded_at_utc` set on first **published** persist only; unchanged after HOLD retry |
| `force=True` before slot | **No** persist (`daily_pick_creation_open` enforced) |
| Legacy same-day | v2 published for **D** exists → reader must not surface legacy **`date==D`** as current |
| Legacy coexistence | Disk has legacy `date=D` + no v2; after 13:05 v2 created; reader prefers v2 when published |
| Upsert | Two writers same `pick_id` → one row (lock) |
| Fence timeout | Token revoked; schedule disabled; boot completes; hero still §3 |
| Cold boot | Creation closed → next slot, not 45s persist (`pick_scheduler`) |
| Read-only paths | No `select_daily_pick` before slot (homepage / story_path pattern) |
| Contract | `tests/test_endpoint_contract.py` unchanged |

**Standing gate:** do not bump `DAILY_PICK_TICK_TIMEOUT_SECONDS` or unmute `LOOP_STALL_GUARD_KILL`.

---

## 8. Deploy & risks

- **Env:** `DAILY_PICK_SLOT_UTC_HOUR=13`, `DAILY_PICK_SLOT_UTC_MINUTE=5`; rollover **13:00** documented in `DEPLOY.md`.
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
