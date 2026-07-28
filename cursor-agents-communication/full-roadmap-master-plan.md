# Full roadmap master plan (review before approve)

**Created:** 2026-07-28  
**Baseline main:** `d316346` (ops evidence + calibration shipped)  
**Rule:** **No phase starts until the previous phase is merged, deployed, and human-reviewed.**

Each phase ends with a **Review Gate** checklist. Do not approve the next phase until every box is ticked.

---

## Phase 0 — Subnet display names (BUILD NOW)

**Problem:** Pump desk and hydrate showed `SN78`, `Unknown`, or stale TMC labels (`Ralph`) because paths used `registry_subnet_rows()` only; remote taostat JSON stops at SN74; TaoStats identity was skipped.

**Branch:** `cursor/subnet-name-fix-4988`  
**Lock:** `subnet-display-names-lock.md` (create on approve)

| Deliverable | Files |
|-------------|-------|
| `display_name_for_netuid()` + TaoStats fallback | `internal/subnet_names.py` |
| `load_subnets_for_display()` TMC-first | `internal/subnets/feed.py` |
| Pump API + `/pump` + desk snapshot | `server.py`, `internal/pump/desk_snapshot.py` |
| Hydrate `/api/subnets` 4s TMC timeout | `server.py` `_get_subnets_hydrate` |
| Pump JS uses `resolveSubnetDisplayName` | `cockpit_hydrate.js`, `pump_map.js` |
| Message intel trending names | `internal/message_intel/engine.py` |
| Tests | `tests/test_subnet_display_names.py` |

**Verify before merge:**
```bash
pytest tests/test_subnet_display_names.py tests/test_subnet_names.py tests/test_pump_alert.py -q
curl -s https://subnet-dashboard.fly.dev/api/pump-alerts | jq '.alerts[0].name, .hero.name'
# Expect human names for netuids on desk, not bare SN{n} when TMC has data
```

**Review Gate 0 (human — required before Phase 1):**
- [ ] PR merged + Fly deploy green
- [ ] Pump desk homepage + `/pump` show correct names for active ladder rows
- [ ] Council pick / weighed room names still correct (no regression)
- [ ] `/api/subnets` meta shows `taomarketcap` or merged when feed succeeds
- [ ] Ditto: supersede Jul 27 `pump-desk-automation` WARN memories (stale)

---

## Phase 1 — Ditto automation migration (docs + human ops)

**Problem:** Ditto still runs obsolete Pump Desk fetch automation; Council Health Monitor can timeout on 3 API storm; memories lag code.

**Branch:** `cursor/ditto-automation-playbook-4988`  
**Deliverable:** `ditto-automation-migration-lock.md` + update `docs/ditto-council-health-artifacts.md`

| Action | Owner |
|--------|-------|
| DISABLE Pump Desk Intelligence Snapshot (`8afd9502…`) | Ditto / human |
| Health Monitor → `learning_outcomes/latest.json` | Ditto |
| KEEP Daily Brief, Weekly Learning, Health Monitor (3 jobs) | Ditto |
| `save_memory` on ALERT / audit MISS / WATCH escalation | Ditto |
| Supersede stale pump-automation WARN memories | Ditto |

**Verify:**
- [ ] Ditto automation run history: no pump HTTP fetch after disable date
- [ ] Manual Health Monitor read from artifact succeeds
- [ ] Wed scheduled run succeeds (or manual dry-run)

**Review Gate 1 (human — required before Phase 2):**
- [ ] Ditto confirms playbook executed
- [ ] Docs PR merged
- [ ] No duplicate 15m pump fetches in automation logs

---

## Phase 2 — Evidence soak + criteria (monitor, no product code)

**Problem:** Need defined pass/fail for Track 1 publish gate + audit + outcome WATCH.

**Branch:** `cursor/track1-soak-lock-4988`  
**Deliverable:** `track1-soak-lock.md`

| Checkpoint | When | Pass |
|------------|------|------|
| Pick audit | Nightly 23:45 UTC | `verdict: PASS` (or documented MISS + fix) |
| Outcome snapshot | 6h + 04:50 UTC | `learning_outcomes/latest.json` fresh |
| Council Health | Wed Sun 05:00 UTC | Auto run OK |
| Publish rate | Day 7 | LONG vs HOLD stable under #551 calibration |
| Publish rate | Day 14 | Human sign-off or gate adjustment PR |

**Queries:**
```bash
curl -s https://subnet-dashboard.fly.dev/api/ops/evidence | jq .
curl -s https://subnet-dashboard.fly.dev/api/learning/health | jq '.status, .daily_pick'
```

**Review Gate 2 (human — required before Phase 3):**
- [ ] ≥7 days soak data recorded in Ditto memory
- [ ] No integrity gate failures
- [ ] Pick audit MISS streak ≤1 (with fix deployed)
- [ ] `track1-soak-lock.md` merged

---

## Phase 3 — Subnet Summers Telegram W1–W3

**Problem:** W0 shipped (#549) but lock AC unchecked; W1–W3 not sliced.

**Canon:** `subnet-summers-telegram-lock.md`

| Wave | Branch prefix | Merge gate |
|------|---------------|------------|
| **W0 closeout** | Mark AC done, fix hydrate if needed | PR + deploy + 390px check |
| **W1** Message expand / verdict + price snapshot | `cursor/ss-tg-w1-4988` | PR + contract + manual Telegram desk |
| **W2** High-conviction strip → Living Focus | `cursor/ss-tg-w2-4988` | PR + hydrate handoff test |
| **W3** Outcomes proof band | `cursor/ss-tg-w3-4988` | After W1–W2 soak |

**Review Gate 3 (per wave):**
- [ ] Wave PR merged + deploy
- [ ] `pytest tests/test_summers_telegram_desk.py` + contract green
- [ ] Human: Subnet Summers desk on 390px
- [ ] **Stop:** do not start W2 until W1 gate cleared

---

## Phase 4 — Accuracy lift (post-soak)

**Problem:** 33% directional accuracy → Council Health WATCH 67. Outcome harness reports; does not fix.

**Pre-gate:** Phase 2 complete (14d soak or explicit early sign-off).

**Branch:** `cursor/accuracy-lift-4988`  
**Lock:** `accuracy-lift-lock.md`  
**Pre-read:** `s25-calibration-oracle-plan.md` (reconcile with #551 on main)

| Slice | Intent |
|-------|--------|
| A | Measurement dashboard artifact: 7d/30d accuracy by expert, regime, horizon |
| B | Weight nudge audit — confirm online path only |
| C | Small scoring experiments (capped soft features) with pytest proof |

**NON-GOALS:** LLM nightly trade grader; auto-merge from automation.

**Review Gate 4:**
- [ ] Measurement slice merged + artifact on volume
- [ ] 30d trend documented in Ditto before scoring experiments
- [ ] Each experiment PR separate with backtest / pytest

---

## Phase 5 — Optional ops hardening

Only after Phase 2 gate:

| Item | Branch | Gate |
|------|--------|------|
| Cursor Automation MISS investigator | Human UI + lock prompt | Manual |
| GHA Slack/email on `ops-evidence` alert | `cursor/ops-paging-4988` | Dry-run false positive check |
| Merge PR #532 ditto-handoff protocol | docs only | Board sync |

---

## Phase 6 — Deferred / decision required

| Item | Status | Decision |
|------|--------|----------|
| **#449** subnet connections full | Draft PR | Revive with phased lock or close |
| **#455** social conviction evidence | Draft PR | Rebase post-stability or close |
| **#474** banner synth/desearch | Draft PR | Close or one-line UI |
| **e7fde567** full pump desk checklist | Deferred | New lock if triad/ladder/mobile polish wanted |
| **Wave D** chat completion | `post-stability-sprint-plan.md` | After accuracy or product priority |
| Chutes live chat / billing | Out of scope | — |

---

## Architecture (stable — do not replan)

```
Fly worker: pick audit · pump snapshot · outcome snapshot
Ditto: briefs · weekly learning · health monitor (artifact mode)
Cursor: code · PRs · deploy guard
Evidence: data/pick_audits · pump_desk · learning_outcomes · GET /api/ops/evidence
```

---

## Approval template (for you)

Copy when signing off each phase:

```text
Phase N APPROVED — merge verified, deploy green, review gate checked.
Proceed to Phase N+1.
```

Or:

```text
Phase N HOLD — [reason]. Do not start Phase N+1.
```

---

## Immediate next step (pending your approve on Phase 0)

1. Review PR `cursor/subnet-name-fix-4988`
2. Tick Review Gate 0 after deploy
3. Then approve Phase 1 Ditto playbook
