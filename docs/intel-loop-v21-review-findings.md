# Intel Loop v2.1 PR #1034 — review findings

Activity log for cross-phase handoff. GitHub branch state and tests are authoritative.

## Phase 1 — Truth (2026-08-24T10:31Z)

**Evidence tier:** confirmed from current code (git/gh)

| Item | Value |
|------|-------|
| PR | #1034 OPEN, draft, MERGEABLE |
| Branch | `cursor/intel-loop-v21-f6eb` |
| HEAD | `e41343b1c20872dd0465a7fd61d062a99439864f` |
| Base | `main` @ `676d4c6639e56401505632673480d6b7c8530e2a` |
| Diff | 18 files, +689 / −51 (no `data/*`) |

**Dirty tree (preserved):** runtime `data/*.json`, pump snapshots, untracked pick_score files.

**Uncommitted local:** `docs/intel-loop-v21-report.md` (`coverage_known` in P0-A table).

---

## Phase 2 — Static audit (2026-08-24T10:31Z)

**Evidence tier:** confirmed from current code

All eight live paths in diff satisfy additive honesty requirements:

- `/api/pump-alerts` — `attach_pump_freshness`, `_mark_stale` + `prior_status`
- WorkerVolumeProxy degraded — `status=degraded` + `handler_stale=True`
- Ladder `?summary=1` — full `coverage_meta` including `coverage_known`
- `/api/subnets` — `handler_status`, `enrichment_status`, null fallback metrics
- `/listener` — 308 → `/subnetsummer`
- `/subnetsummer` — outer try + TemplateResponse fallback + static HTML escape
- Banner — SSR + `cockpit_hydrate.js` reads `freshness` fields only

**Issue boundaries:** pump freshness, subnets timeout, summer SSR, `living_focus_ts` treated as **independently convergent** (no shared root cause proven).

---

## Phase 3 — Focused tests (2026-08-24T10:31Z)

**Evidence tier:** confirmed from current tests

```bash
PYTHONPATH=. pytest tests/test_intel_loop_v21.py tests/test_pump_desk_payload.py \
  tests/test_subnets_source_meta.py tests/test_summers_telegram_desk.py \
  tests/test_pump_alert.py::test_api_pump_alerts_route tests/test_worker_volume_proxy.py -v
```

**Result:** 62 passed in 6.62s

Not a full-suite claim.

---

## Phase 4 — Local runtime (2026-08-24T10:31Z)

**Evidence tier:** confirmed locally at runtime (PR branch, PORT=5000)

| Probe | Result |
|-------|--------|
| `/health` | 200 |
| `/listener` | 308 → `/subnetsummer` |
| `/subnetsummer` | 200 |
| `/pump` | 200 |
| `/api/pump-alerts` | success, freshness=fresh, data_available=true (max_row_age_seconds=8415 ≈ 2.3h; threshold `PUMP_ROW_STALE_SECONDS` default **21600** (6h) in `desk_payload.py` — age below threshold ⇒ `freshness=fresh`, not stale) |
| `/api/subnets?limit=500` | success, n=75 0..74, handler_status=ok, enrichment_status=live |
| `/api/pump-ladder/state?summary=1` | coverage_known=true, feed_stalled=true |

Log: `/opt/cursor/artifacts/pr1034_local_runtime.log`

---

## Phase 5 — Browser (2026-08-24T10:32Z)

**Evidence tier:** confirmed locally at runtime (Gemini computerUse)

- All four pages load; `/subnetsummer` 200 locally
- No `living_focus_ts` TypeError this session (independent issue when present)
- `/api/pump-alerts` JSON includes `freshness`; subnets meta includes `handler_status`; ladder meta includes `coverage_known`
- `/pump` banner hidden when `freshness=fresh` (expected); no false stale banner

Not a “no client defects” claim.

---

## Phase 6 — Production (2026-08-24T10:31Z)

**Evidence tier:** confirmed in production (main/pre-deploy, not PR branch)

| Endpoint | Result |
|----------|--------|
| `/api/subnets?limit=500` | 200, status=timeout, n=75 0..74, frozen missing, honesty meta absent |
| `/api/pump-alerts` | 200, status=success, 5 rows Aug-17, freshness absent |
| `/api/pump-ladder/state?summary=1` | 200, n=200, frozen present, coverage_meta absent |
| `/listener` | 308 |
| `/subnetsummer` | **500** Internal Server Error |

Log: `/opt/cursor/artifacts/pr1034_prod_probes.log`

---

## Phase 7 — Implementation decision

**Code changes necessary:** No scoped gap confirmed on current branch.

Default outcome: **review report only**.

---

## Remaining human decisions

Frozen netuids `{75,80,87,90,118}`: **fix shipped** — `load_subnets_for_pump_signals()` now unions committed registry + ladder keys missing from merged/TMC clip (human authorized "Fix" after policy question). Display-only vs true exclusion vs leave-as-is is resolved as **true feed inclusion** for registry/ladder gaps, not a pinned drop list.

Prod `/subnetsummer` 500 fixed on PR branch locally; requires merge + deploy to Fly.

**Amendment C (historical):** prod failure class locally reproduced as `verdict.conviction` → Jinja `UndefinedError` in message-intel macros; PR adds float coerce + outer fallback.

---

## Binding confirmations

- Feed membership not changed
- Pump scan loop not restarted
- Telegram not enabled
- Inline-worker topology not changed
- API fields not renamed or removed
## Phase 9 — Luna review (2026-08-24T10:35Z)

Initial BLOCK: report HEAD/`living_focus` wording. Corrected in `docs/intel-loop-v21-report.md` at review commit.

**Evidence tier:** confirmed from current tests + code — report-only; no scoped implementation gap.

**Draft → ready:** Luna SHIP on report-only completion after doc fixes (2026-08-24). Awaits human authorization to mark draft ready.

---

## Closeout acceptance (2026-08-24)

**Verdict:** Accepted as Intel Loop **review closeout** (not an implementation plan). Human decisions pending: frozen-netuid policy, merge/deploy authorization, draft→ready.

**Live HEAD re-check:** `62d0c25da691dd146b3af0ccd4bea53ba7967f57` — matches GitHub PR #1034 at closeout time. Re-verify before any action.

**Luna SHIP:** reported external review evidence from this agent session; does not replace current code/test re-verification.

**Artifact paths** (`/opt/cursor/artifacts/pr1034_*.log`): session-local; another Cursor VM may not have them — rely on repo docs and re-run probes if needed.

**Sentry Path A:** read-only repo/config review and local SDK discovery may proceed. Do not set Fly `SENTRY_DSN` secrets, deploy, or activate prod alerting during active Intel Loop merge/deploy decision; secret sets restart Fly machines. Do not push Sentry or doc changes to `main` concurrently with Intel Loop merge/deploy.

---

## Post-deploy verification (2026-08-24T15:00Z)

**Evidence tier:** confirmed in production (after Fly Deploy run `32740425371`)

| Item | Value |
|------|-------|
| Deploy run | https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/32740425371 |
| Deployed SHA | `95f7e0c4` (matches merge commit) |
| Deploy completed | 2026-08-24T14:47:24Z |
| First probe | 2026-08-24T14:48:27Z (~1 min post-green) |
| Verdict | **POST-DEPLOY PASS** |

**Step 1 subnets:** `handler_status=ok`, `enrichment_status=live`, `generated_at` present, `data_available=true`, source=blockmachine, n=75 (0–74). Null-metric registry-fallback path not observed this window (live blockmachine only).

**Step 2 pump-alerts:** `freshness=stale`, `freshness_scope=rows`, `max_row_age_seconds=607131`, `status=success` (7d-old rows honestly stale).

**Step 3 ladder (rerun 15:00Z):** `coverage_known=true`, `signal_row_count=200`, `missing_from_feed_count=0`, frozen `{75,80,87,90,118}` tracked, `missing_frozen=[]`, `feed_stalled=false`.

**Step 4:** listener 308→/subnetsummer; three summer probes (300s apart) all HTTP 200.

**Sentry Path A:** unlocked for read-only production verification (SENTRY_DSN set/alert activation still separately gated).

Log: `/opt/cursor/artifacts/post_deploy_probes.log`

---

## Post-deploy verification — formal plan run (2026-08-24T16:34Z)

**Evidence tier:** confirmed in production (plan implementation; Fly Deploy run `32740425371`)

| Item | Value |
|------|-------|
| Deploy run | https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/32740425371 |
| Deployed SHA | `95f7e0c4` (`headSha` = merge commit) |
| Deploy completed | 2026-08-24T14:47:24Z |
| Probe window | 2026-08-24T16:23:31Z – 16:34:54Z |
| Verdict | **POST-DEPLOY PASS** |

**Step 0:** PR #1034 MERGED @ `95f7e0c4`; post-merge deploy success; no secrets changed.

**Step 1 subnets:** HTTP 200; `status=timeout`, `handler_status=timeout`, `enrichment_status=live`, `generated_at` present, `data_available=true`, n=75 (0–74), source=blockmachine. Honesty meta **PASS**. Null-metric spot check on blockmachine timeout path: `emission=0.0`, `emission_available` absent — registry-fallback `_null_unfetched_metrics` path **not exercised** (`unavailable-pending` for that specific check).

**Step 2 pump-alerts:** `freshness=fresh`, `freshness_scope=rows`, `data_available=true`, `max_row_age_seconds=1206`, `status=empty`, oldest row ~20m — **PASS** (freshness metadata present; rows < 6h threshold). Degraded proxy: **unavailable-pending** (circuit closed; no outage induced).

**Step 3 ladder:** `coverage_known=true`, `signal_row_count=200`, `missing_from_feed_count=0`, `feed_stalled=false`, frozen `{75,80,87,90,118}` all present, `missing_frozen=[]` — union **PASS**.

**Step 4:** listener HTTP 308 → `/subnetsummer`. Summer probes (300s spacing): all HTTP 200, rendered HTML (sizes 45310/45310/45310) — **PASS**.

**Step 5 browser:** unavailable-pending (API verification sufficient).

**Sentry Path A:** unlocked for read-only production verification.

**Confirmations:** no membership/topology change, no scan-loop restart, Telegram not enabled, API fields additive-only, hydration untouched, dirty runtime data preserved, no unrelated changes during verification.

Log: `/opt/cursor/artifacts/post_deploy_probes.log`
