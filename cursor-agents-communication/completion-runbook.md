# Completion runbook — merge → babysit → next

**Created:** 2026-07-30  
**main:** `0d52516` (post #670 pre–Aug 4 unblock)  
**Cadence:** one PR → merge → `./scripts/babysit_phase.sh sprint` + `./scripts/check_learning_loop.sh` → Ditto STATUS → next PR

---

## Executive summary

| Track | Status |
|-------|--------|
| Master sprint (M0–FQ-4) | **DONE** |
| Pre–Aug 4 wave (PR1–PR10) | **IN PROGRESS** — PR1/2/5/R partial in #664–#670 |
| Wave 3 (Slice 7 accuracy lift) | **GATED** — H2 soak GO **2026-08-04** |
| Human lanes H2–H7 | Parallel (never block agent PRs) |

**North star:** Ship Wave 1+2 polish before Aug 4; run soak checkpoint; only then Wave 3.

---

## Cadence (every PR)

```bash
# After merge + Fly deploy (~5–10 min)
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint
BASE=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
./scripts/soak_review_snapshot.sh | jq '.checks.combined_angles, .suggested_decision'
```

| Babysit | Expect |
|---------|--------|
| `health` | 3/3 |
| `lc` | robots 200; NFA + og-share in HTML (WARN ok on cached shell) |
| `ld` | alerts hidden when disabled; portfolio 200 |
| `acc0` | `ledger.gap=false` |
| `fq4` | `combined_angles` present; WARN `graded=0` until picks resolve |
| `pp0/pp1/pp2` | OK; WARN if no ladder segments yet |

**Strict gates (fail = stop, do not tune):**

- `./scripts/babysit_phase.sh fq4` — requires `graded > 0`
- Wave 3 PR11+ — requires H2 **GO** on 2026-08-04

---

## Done ✅

| Item | PR / note |
|------|-----------|
| Master sprint M0 → FQ-4 | #647–#670 |
| Acc-0 heal + worker rebalance | #650 path, #668–#669 |
| Combined angles effectiveness | #664, #665 |
| SS-TG H1 cleared + 390px polish (lite) | #670 |
| Pump hero D+C-lite | #670 |
| Empty-state kit (partial) | #663 + message_intel_feed |
| Soak snapshot + combined_angles block | #670 |
| g0 SS-TG W0 markers | #670 |

---

## Agent queue (execute in order)

Branch prefix: `cursor/<slug>-7728`

| # | PR | Branch slug | Status | Lock |
|---|-----|-------------|--------|------|
| 1 | Combined effectiveness | — | **DONE** #664+#665 | `combined-angles-lock.md` |
| 2 | SS-TG V5 visual (lite) | — | **DONE** #670 | fonts + 390px |
| 3 | Listener reconnect + empty kit | `ss-tg-listener-empty-kit` | **NEXT** | PR3 below |
| 4 | Topic chips v1 | `ss-tg-topic-chips-v1` | pending | |
| 5 | Pump hero D+C-lite | — | **DONE** #670 | |
| 6 | Sticky spine + status rail | `visual-sticky-spine` | partial (sticky exists; badge 390px) | |
| 7 | Evidence sub-panels | `visual-evidence-panels` | pending | |
| 8 | `/pump` desk parity | `pump-full-desk-parity` | pending | |
| 9 | Mind map mobile collapse | `mindmap-mobile-collapse` | pending | |
| 10 | Living Focus CTA polish | `lf-cta-polish` | pending | |
| R | SS-TG 390px reactive | `finish-slice5-ss-tg-390px` | only if g0 fails | |

**Detail:** `pre-aug4-polish-plan.md` (per-PR AC)

---

## Wave 3 — GATED (2026-08-04 H2)

| # | Work | Gate |
|---|------|------|
| 11 | Slice 7a accuracy measurement dashboard | H2 **GO** |
| 12 | Combined weight tune (optional) | H2 GO + `graded_n ≥ 20` |
| 13+ | Weight audit / capped experiments | separate PRs |

**Checkpoint command:**

```bash
./scripts/soak_review_snapshot.sh | jq .
curl -fsS https://subnet-dashboard.fly.dev/api/ops/evidence | jq '.combined_angles'
```

---

## Human lanes (parallel)

| # | Task | When |
|---|------|------|
| H1 | 390px SS-TG | **Cleared** 2026-07-30 |
| H2 | Soak day 7 GO/HOLD | **2026-08-04** |
| H3 | Soak day 14 | 2026-08-11 |
| H5 | W6 Telegram bot | optional |
| H6 | `TAOSTATS_API_KEY` | optional |
| H7 | `WRITE_API_TOKEN` | optional |

**Ops:** `AuthKeyDuplicatedError` → rotate `TELEGRAM_SESSION_STRING` on worker.

---

## Housekeeping

| Task | Action |
|------|--------|
| Close stale PR #650 | Superseded by main ledger_heal — close as duplicate |
| Draft PR triage | #641 plan merged via #670; close draft or mark superseded |
| Board sync | Update `main=` SHA after each merge |
| Ditto STATUS | `save_memory` after each merge |

---

## Definition of done (this runbook)

- [ ] PR3–PR10 merged + babysit green (WARN-only gates OK)
- [ ] `g0_phone_qa.sh` exit 0 on prod
- [ ] Strict `fq4` passes when `graded > 0` (monitor; no code change)
- [ ] Aug 4 checkpoint run; H2 decision recorded
- [ ] If H2 GO: PR11 merged; board Phase 4 → ACTIVE
- [ ] Optional PR12 only if evidence + human approve

**Out of scope until H2 GO:** scoring changes, combined 0.70/0.30 tune, Chutes billing, custom domain.
