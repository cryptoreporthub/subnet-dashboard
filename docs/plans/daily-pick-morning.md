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
3. **`selection_recorded_at_utc`** (name in impl PR) set **once** on first persist for that `pick_id`; **never** updated on HOLD/regen/retry (fixes `:321/:364` restamp bug for v2 rows).
4. **One reader rule everywhere** (§3).
5. **Generation-token write fence** for concurrent resolver/pick RMW (§5) — **never block process boot**; on hard timeout: revoke token, keep serving last published pick, disable new scheduler ticks, expose unhealthy — ops recovers.

---

## 3. Shared pick-day + reader rule

**Module:** `internal/council/pick_day.py` (new).

| Constant | Default | Role |
|----------|---------|------|
| `PICK_DAY_ROLLOVER_UTC_HOUR` / `MINUTE` | `13` / `0` | Pick-day string advances |
| `DAILY_PICK_SLOT_UTC_HOUR` / `MINUTE` | `13` / `5` (env at deploy) | Scheduler slot (existing env names) |

**Rollover:** if `now.utc() < 13:00`, pick day = previous calendar date; else today’s calendar date (`pick_day_str()`).

**Creation gate:** persist allowed when `now >= pick_day_start_utc(pick_day_str()) + slot offset` (default **13:05** on that pick day).

### Published row

**`is_published_daily_pick_row(rec)`:** not `scheduler_hold`; `action` in `LONG`/`BUY`; `pick` is a dict.

### One shared reader rule (normative)

For current **`pick_day = pick_day_str()`**:

1. Prefer **published v2** row with **`pick_id == f"v2:{pick_day}"`** (or `schema_version >= 2` and matching `pick_day`).
2. Else **latest published** row in `daily_picks.json` (any schema) with **`pick_day` or legacy `date` ≤ pick_day** — **never** HOLD / `scheduler_hold` / pending-only.
3. Meta may set **`prior_pick_day: true`** when showing a row whose key ≠ `pick_day`.

**Pre/post cutover:** legacy v1 rows and v2 rows **coexist**; reader never requires migration. **13:00:30 UTC** test: show prior published row, not empty hero.

**Migration gate removed:** hero uses **`last_good_published_pick`** / rule above always — no 503 for missing marker.

---

## 4. Writers

- **`_upsert_today` → upsert by `pick_id`** (v2) under existing **`daily_picks.json` lock** (`daily_pick_engine.py:72-88`, `:96-137`) — atomic RMW; legacy rows keyed only by `date` remain as-is.
- **`get_or_create_today_pick`:** if not `force` and not `daily_pick_creation_open()`, **no** `select_daily_pick` / `_save`; read paths use §3 only.
- **Scheduler:** when creation closed, schedule **`_seconds_until_daily_slot()`** (`pick_scheduler.py:69-73`), **not** 45s early create (`:273` target change).
- **Audits (new only):** `pick_selection_audit` writes **`data/pick_audits/by_pick_id/v2_<pick_day>.json`** (or embed `pick_id` in payload); **legacy date-keyed audit files unchanged** and still valid for old rows.
- **Post-marker legacy-key refusal removed** — replaced by v2 `pick_id` upsert; old code paths must not overwrite v2 row for same calendar day without matching `pick_id`.

---

## 5. Generation-token write fence (resolver + pick)

**Pattern (existing):** `PredictionResolverScheduler` uses **`_cycle_generation`** / **`_persist_owner_gen`** (`internal/council/resolver_scheduler.py:434-436`, `:778-790`, owner checks `:1014`, `:1126`, `:1156`).

**Normative:**

- Under **same lock as pick JSON RMW** (`daily_picks.json.lock`), pick persist checks **active write token** (shared with resolver persist gate — impl names **`daily_pick_write_token`**).
- **Bounded wait** (default **3600s**, env) for in-flight resolver cycle before pick slot write.
- **On timeout:** **revoke token** (resolver abandon path mirrors `_abandon_inflight_cycle`); **do not block boot**; **disable** new daily pick schedule until token re-armed; **continue serving** §3 last published; `/health` **`daily_pick_write_fence_timeout: true`**.
- **Never** unbounded wait; **never** fail-closed boot blocking migration (migration removed).

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
| SimiVision | `caution_cells.py:26`, `:56` | `pick_day_str` |
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
| v2 row | `pick_id=v2:D`, `selection_recorded_at_utc` unchanged after HOLD retry |
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
