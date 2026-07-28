# Post-audit sprint — phased plan (merge + babysit each)

**Status:** ACTIVE  
**Created:** 2026-07-28  
**Baseline:** `main` @ post-#557 (`79715a0` area) — audit P0/P1 + SS-TG W0–W3 **DONE**  
**Cadence:** One phase → one PR → merge → `./scripts/babysit_phase.sh <phase>` → human spot-check → next phase  
**Handoff:** `ditto-cursor-handoff.md` · `audit-remediation-lock.md` (DONE) · `subnet-summers-telegram-lock.md` (W0–W3 DONE)

---

## What’s already shipped (do not re-litigate)

| Area | PRs |
|------|-----|
| Audit P0/P1 | #555 ops/live, cached readiness, write auth, SSRF |
| Audit P2 | #556 CSP-RO, HSTS, nosniff |
| SS-TG W0–W3 + API errors | #557 detail tap, HC strip, proof band |
| Ops evidence | #550–#551 pick audit, outcome snapshot, calibration |
| Brain / pump / H1 | #544, #548, pump desk chain |

**Prod snapshot (2026-07-28):** worker alive · listener running · Telegram proof ~35% / 143 graded · `/api/ops/live` &lt;100ms

---

## Execution order

```text
Phase A  Ops quick wins          ← WRITE_API_TOKEN, metrics, board sync
  → Phase B  #552 polish         ← outcome boot tick + stale alert guard
  → Phase C  Worker split v2     ← structural wedge fix (needs volume plan)
  → Phase D  Security housekeeping ← global api_errors + CSP enforce window
  → Phase E  SS-TG W4            ← 24h summary strip
  → Phase F  SS-TG W5            ← feed noise filters
  → Phase G  SS-TG W6            ← in-chat /summary bot (human gate)
  → Phase H  Soak review         ← Track 1 + pick audit + council health (monitor)
```

**Hard gate:** Do not start **Phase C** until Phase A+B babysit green.  
**Hard gate:** Do not start **Phase G** until human confirms Bot API token + mod permission in Summers group.

---

## Babysit contract (every phase)

Run after merge + Fly deploy (~3–5 min):

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh <phase>
```

Minimum manual checks:
1. `GET /health` — 200 in &lt;2s (3 probes)
2. `GET /api/ops/live` — 200, `worker_peer.alive: true`
3. `GET /` — 200, cockpit shell loads
4. Phase-specific asserts (see each phase AC)

If babysit fails: **stop queue**, fix or rollback, re-babysit before next phase.

---

## Phase A — Ops quick wins

**Lock:** `ops-quick-wins-lock.md`  
**Branch:** `cursor/phase-a-ops-quick-wins-1d2f`  
**Model:** Composer fast

| Work | Detail |
|------|--------|
| A1 | Document + script `scripts/set_write_api_token.sh` (generate token, `flyctl secrets set WRITE_API_TOKEN`) |
| A2 | `ENABLE_METRICS=1` in `fly.toml` (or env-gated); confirm `/metrics` in contract |
| A3 | Sync `board.md`, `audit-remediation-lock.md`, `subnet-summers-telegram-lock.md` → W0–W3 DONE |
| A4 | `babysit_phase.sh` scaffold with phase A checks |

**AC:**
- [ ] `DEPLOY.md` documents WRITE_API_TOKEN + metrics toggle
- [ ] Babysit phase A passes (health, ops/live, optional metrics 200)
- [ ] Board reflects `main` + completed audit/SS-TG

**Babysit:**
```bash
curl -fsS $BASE/health
curl -fsS $BASE/api/ops/live
curl -fsS $BASE/metrics  # 200 if ENABLE_METRICS=1
```

**Human (optional same day):** run `flyctl secrets set WRITE_API_TOKEN=…` when ready to lock writes.

---

## Phase B — #552 polish (outcome loop boot)

**Lock:** `outcome-boot-polish-lock.md`  
**Branch:** `cursor/phase-b-outcome-boot-polish-1d2f`  
**Predecessor:** board row “#552 polish”

| Work | Detail |
|------|--------|
| B1 | Outcome snapshot / price loop starts within 2 min of boot (not 5 min defer) |
| B2 | Stale alert guard — don’t fire “stalled” during known boot defer window |
| B3 | `GET /api/message-intel/status` → `outcomes.live` honest within 3 min post-deploy |

**AC:**
- [ ] `tests/test_message_intel_outcomes.py` + outcome snapshot tests green
- [ ] Post-deploy: `outcomes.running: true` within 3 min
- [ ] No false “learning_loop_stalled” in first 5 min after deploy

**Babysit:**
```bash
curl -fsS $BASE/api/message-intel/status | jq '.outcomes,.listener'
curl -fsS $BASE/api/learning/health | jq '.status,.resolver.running'
```

---

## Phase C — Fly worker split v2

**Lock:** `fly-worker-split-v2-lock.md`  
**Branch:** `cursor/phase-c-worker-split-v2-1d2f`  
**Canon:** `docs/fly-web-worker-split.md` (v2 section)

| Work | Detail |
|------|--------|
| C1 | Second Fly process group `worker` with `RUN_MODE=worker` |
| C2 | Volume attach strategy — worker owns writes; web read-only JSON/SQLite |
| C3 | `fly.toml` + `fly_web_entrypoint.sh` — web no longer forks inline worker when v2 enabled |
| C4 | Readiness reports `worker_mode: split` + `worker_peer.alive` cross-machine |
| C5 | Deploy runbook in `DEPLOY.md` — scale web=1 worker=1, rollback steps |

**AC:**
- [ ] `GET /health` &lt;2s while 5× `/api/pump-alerts` + `/api/message-intel` in flight
- [ ] Resolver + pump scheduler logs on **worker** machine only
- [ ] No split-brain on `data/` (single writer)
- [ ] Contract + `test_prod_stability.py` green

**Babysit:**
```bash
./scripts/verify_prod.sh          # health + pump subset
curl -fsS $BASE/api/ops/readiness | jq '.worker_mode,.worker_peer'
# 10× parallel light API — none 503 >10s
```

**Risk:** Requires human Fly ops if region/volume mismatch. **Rollback:** scale worker=0, re-enable inline worker.

---

## Phase D — Security housekeeping

**Lock:** `security-housekeeping-lock.md`  
**Branch:** `cursor/phase-d-security-housekeeping-1d2f`

| Work | Detail |
|------|--------|
| D1 | `internal/api_errors.public_error` on **learning** + **signals** write routes (top 10 leak sites) |
| D2 | CSP: flip `CONTENT_SECURITY_POLICY_REPORT_ONLY` → enforced `CONTENT_SECURITY_POLICY` (tighten script-src if needed) |
| D3 | Rate-limit strict on scan/trigger/investigate endpoints |
| D4 | Proxy-aware rate limit key (`X-Forwarded-For` trust for Fly) |

**AC:**
- [ ] No `str(exc)` in JSON from `/api/learning/*` error paths (grep + tests)
- [ ] Home still loads with enforced CSP (manual browser check)
- [ ] Contract green

**Babysit:**
```bash
curl -sS -D - -o /dev/null $BASE/ | grep -i content-security
# POST without token → 401 when WRITE_API_TOKEN set
```

---

## Phase E — SS-TG W4 (24h summary strip)

**Lock:** `subnet-summers-telegram-lock.md` (W4 section)  
**Branch:** `cursor/phase-e-ss-tg-w4-summary-1d2f`

| Work | Detail |
|------|--------|
| E1 | `build_24h_summary()` in rollup — top subnets, movers, HC count, group pulse |
| E2 | Expose on `meta.summary_24h` in `/api/message-intel` |
| E3 | UI strip between source strip and yesterday hero |
| E4 | Tests `test_summers_telegram_w4.py` |

**AC:**
- [ ] Summary visible on home without drawer open
- [ ] Honest-empty when &lt;10 messages in 24h
- [ ] 390px: no layout break

**Babysit:**
```bash
curl -fsS "$BASE/api/message-intel?limit=1" | jq '.meta.summary_24h'
curl -fsS $BASE/ | grep -o 'message-intel__summary-24h'
```

---

## Phase F — SS-TG W5 (feed filters)

**Lock:** `subnet-summers-telegram-lock.md` (W5 section)  
**Branch:** `cursor/phase-f-ss-tg-w5-filters-1d2f`

| Work | Detail |
|------|--------|
| F1 | Client filters: min conviction slider/chips (60/70/80), subnet chip filter |
| F2 | Optional query params on `/api/message-intel` (`min_conviction`, `netuid`) — backward compatible |
| F3 | Persist filter prefs in `sessionStorage` |
| F4 | Tests + 390px QA |

**AC:**
- [ ] Filter state survives refresh (sessionStorage)
- [ ] Empty state copy when filters exclude all rows
- [ ] No new routes required for contract (query params only)

**Babysit:** Manual 390px — apply 80% filter, confirm feed shrinks; reset shows full feed.

---

## Phase G — SS-TG W6 (in-chat /summary bot)

**Lock:** `subnet-summers-telegram-w6-bot-lock.md`  
**Branch:** `cursor/phase-g-ss-tg-w6-bot-1d2f`  
**GATE:** Human provides `TELEGRAM_BOT_TOKEN`, bot added to group as admin or with post permission

| Work | Detail |
|------|--------|
| G1 | Bot handler: `/summary` → post 24h rollup to group |
| G2 | Rate limit + opt-in env `TELEGRAM_SUMMARY_BOT=on` |
| G3 | Link back to site desk in message |
| G4 | Does **not** replace user-session listener |

**AC:**
- [ ] `/summary` in test chat (or staging group) posts formatted summary
- [ ] Bot off by default in `fly.toml`
- [ ] No council pick steering from chat (quarantined)

**Babysit:** Human posts `/summary` in OfficialSubnetSummer; confirm bot reply + site link.

---

## Phase H — Soak review (monitor gate)

**Lock:** `track-1-soak-review-lock.md`  
**Not a single PR** — review checkpoint after 7–14d from #551 calibration

| Check | Source |
|-------|--------|
| Daily pick publish rate | `data/daily_picks.json`, `/api/daily-pick` |
| Pick audit PASS rate | `data/pick_audits/`, nightly script |
| Council health trend | `learning_outcomes/latest.json`, Ditto monitor |
| Telegram proof trend | `meta.telegram_proof` — improving or stable? |

**Outcome:** GO / HOLD / adjust calibration gates — document in Ditto + `board.md`.

---

## Branch naming

All branches: `cursor/phase-<letter>-<short-name>-1d2f`

## Model ladder

| Phase | Model |
|-------|-------|
| A, B, E, F | Composer 2.5-fast |
| C (worker split) | Grok medium LOCK → Composer |
| D (security) | Composer + careful CSP manual test |
| G (bot) | Composer; Telethon/Bot API edge cases → Grok if stuck |

---

## Suggested first PR

**Phase A** — `cursor/phase-a-ops-quick-wins-1d2f` (docs, babysit script, board sync, metrics toggle).  
No Fly topology change; safe to merge and babysit same day.

---

## References

- `audit-remediation-lock.md` — DONE
- `subnet-summers-telegram-lock.md` — W0–W3 DONE
- `docs/fly-web-worker-split.md` — Phase C canon
- `post-stability-sprint-plan.md` — prior wave pattern
- `ops-evidence-master-plan.md` — pick audit + outcome snapshot
