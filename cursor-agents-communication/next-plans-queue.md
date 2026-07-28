# Next plans queue (2026-07-28)

**main:** `d316346` · Ops evidence **DONE** (`ops-evidence-master-plan.md`)  
**Rule:** Ditto thinks → git **lock** → Cursor builds (`ditto-cursor-handoff.md`)

---

## Tier 0 — No new plan (monitor only)

| Item | Why |
|------|-----|
| Ops evidence loop | Shipped #546–#552 |
| Learning loop phases 0–6 | Merged per `learning-loop-full-integration-plan.md` |
| H1 hour watch | DONE #548 |
| Brain trio | DONE #544 |
| Tonight pick audit 23:45 UTC | Evidence only — wait for PASS/MISS |
| Wed Council Health Monitor | Confirm auto-run after 422 fix |
| Track 1 soak | Running — needs criteria doc (Tier 1) |

---

## Tier 1 — Plan needed (discussed; not locked)

### P1 — Ditto automation migration playbook

**Trigger:** Conversation + Ditto memories still show Jul 27 `pump-desk-automation` WARN (stale).  
**Scope:** One-page runbook (not code): disable Pump Desk fetch (`8afd9502…`); Health Monitor reads `learning_outcomes/latest.json`; save_memory on WATCH/ALERT/MISS; keep 3 separate jobs.  
**Owner:** Human + Ditto · **Lock:** `ditto-automation-migration-lock.md` (create)  
**Ditto memory action:** Supersede `7168a6c0`, `ebb292b8`, `a666d868`, `9ac990c8`, `e0738824` pump-desk-automation WARN posts.

### P2 — Subnet Summers Telegram W1–W3

**Trigger:** `subnet-summers-telegram-lock.md` — W0 shipped #549 but AC unchecked; W1–W3 listed.  
**W1:** Message expand / verdict + price snapshot  
**W2:** High-conviction strip + Living Focus handoff  
**W3:** Outcomes proof band (hit-rate story) — **after** message-intel soak  
**Lock:** Update `subnet-summers-telegram-lock.md` → W0 DONE, split W1–W3 slices  
**Owner:** Cursor Agent B territory (message_intel) — confirm board ownership

### P3 — Track 1 soak review (7–14d)

**Trigger:** Board + #543 + #551 calibration in prod.  
**Scope:** Define pass/fail: LONG publish rate, HOLD gate stability, integrity gates, no audit MISS streak.  
**Deliverable:** `track1-soak-lock.md` with review date + metrics queries (`/api/learning/health`, `data/pick_audits/`, publish gate).  
**Owner:** Monitor — human sign-off at day 7 and day 14.

### P4 — Accuracy lift (33% → target band)

**Trigger:** Council Health WATCH 67 / 33% — outcome harness reports; not a deploy bug.  
**Scope:** Measurement plan first (30d rolling, per-expert breakdown, regime tags) — then scoring/weight experiments.  
**Pre-read:** `s25-calibration-oracle-plan.md` (may be stale); #551 in prod.  
**Lock:** `accuracy-lift-lock.md` — **do not** start code until soak shows stable publish + audit PASS.  
**NON-GOALS:** LLM nightly trade grader.

### P5 — Pick audit MISS investigator (Cursor Automation)

**Trigger:** `pick-audit-lock.md` recipe — cloud agent cannot create automations.  
**Scope:** Human creates in Cursor Settings; manual or scheduled after `nightly_pick_audit.sh` exit 2.  
**Deliverable:** Copy-paste prompt already in lock — no repo work unless webhook from worker.

### P6 — Ops paging upgrade (optional)

**Trigger:** Discussed optional Slack/email on GHA `ops-evidence` exit 2.  
**Scope:** `.github/workflows/ops-evidence.yml` + secret — small slice after soak proves signal quality.

---

## Tier 2 — Existing plans / drafts (stale or unmerged)

| Artifact | State | Action |
|----------|-------|--------|
| **PR #532** `ditto-cursor-handoff.md` | OPEN draft | Merge — protocol is live in repo |
| `post-stability-sprint-plan.md` | Marked COMPLETE | Wave C–E optional only |
| Wave C **#455** social conviction | DRAFT PR | Plan: rebase or close |
| Wave E **#449** subnet connections | DRAFT PR | Plan: phased lock if revived |
| `post-s30-living-brain-plan.md` §30 causal path API | **Needs lock before build** | Grok/Ditto review → lock file |
| `e7fde567` pump desk full checklist | Deferred in handoff | Reopen only with new lock (triad legs, ladder grid, mobile) |
| `fdc0dccb` Ditto council brief architecture | Partially shipped | Update brief automation to use artifacts + memory index |

---

## Tier 3 — Explicitly out of scope (no plan)

- Chutes billing / live LLM chat replies
- Ditto implementing Python Fly workers
- LLM “was this a good trade?” nightly loop
- Merging Ditto automations into one mega-job

---

## Recommended execution order

```text
Now     P1 Ditto migration playbook + supersede stale memories
        P3 soak criteria doc (parallel, no code)
Wait    Tonight audit · Wed Health Monitor
Next    P2 SS-TG W1 (if Summers launch priority)
After   P4 accuracy lift (post-soak)
Optional P5–P6 automations / paging
```

---

## Ditto memory hygiene (from search)

| Memory / source | Issue | Action |
|-----------------|-------|--------|
| `pump-desk-automation` Jul 27 WARN chain | Pre-#547 worker | Supersede — worker owns snapshots |
| `afc3f5b7` | Says #552 pending | Update — #552 merged `d316346` |
| `fdc0dccb` council brief from live APIs | API storm risk | Plan artifact-first briefs |
| `a927fbae` automations manual in Settings | Still true | P5/P1 reference |
