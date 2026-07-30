# Pre–Aug 4 polish + evidence wave (to completion)

**Created:** 2026-07-29  
**Status:** EXECUTING — human cleared H1 2026-07-30  
**Runbook:** `completion-runbook.md` (merge → babysit → next)  
**Baseline main:** `c8a1146` (post #632 reaction crowns · #638 resolver badge)  
**Canon:** `board.md` · `finish-queue-plan.md` · `combined-angles-lock.md` · `subnet-summers-telegram-lock.md` · `track-1-soak-review-lock.md`  
**Branch prefix:** `cursor/<slug>-6063`  
**Babysit every merge:** `./scripts/babysit_phase.sh c` · `./scripts/check_learning_loop.sh` · Ditto STATUS

---

## Executive summary

Two lanes run until **Track 1 soak day 7 (2026-08-04)**:

| Lane | Energy | Outcome |
|------|--------|---------|
| **A — Evidence** | Slice 4–style measurement | Combined angles hit rates in ops evidence; soak snapshot ready for Aug 4 |
| **B — Flagship polish** | Visual + Telegram UX | V5 desk, listener honesty, topic chips, pump hero D+C-lite, empty-state kit, sticky spine, evidence panels |

**Aug 4 gate (H2)** decides Lane C (Phase 4 accuracy lift / Slice 7). Do **not** tune scoring or Combined 0.70/0.30 before that unless `graded_n ≥ 20` **and** human says “tune now.”

**North stars**

- Cards / borders / calm empty: **`/subnet/{n}`** + Council Weighing empty card  
- Atmosphere / fonts on flagship desks: **Telegram V5 mockup** (`docs/mockups/telegram-pulse-visual-v5.html`)  
- Mono only for SN ids, timestamps, numeric columns — not body/empty/error copy

---

## Human gates (parallel; never blocked on agent PRs)

| # | Task | When | Blocks |
|---|------|------|--------|
| **H1** | 390px SS-TG sign-off (expand, HC, proof, status rail) | Anytime during wave | Slice 5 reactive fixes |
| **H2** | Soak day 7 GO / HOLD / adjust | **2026-08-04** | Lane C / Slice 7 |
| **H3** | Soak day 14 | 2026-08-11 | Final accuracy experiments |
| **H5–H7** | Optional W6 bot / TaoStats / WRITE_API_TOKEN | Anytime | Nice-to-have |

If H1 fails items → insert **PR-R** (Slice 5) after the failing PR’s deploy; do not wait for end of queue.

---

## Locked product decisions

| Decision | Choice |
|----------|--------|
| Hero visual | **D + C-lite** — phase-tinted animated mesh default; soft arc from `progress_series` when ≥2 points |
| Combined weights | **Frozen** 0.70 / 0.30 until Aug 4 + `graded_n ≥ 20` |
| V5 fonts | Telegram pulse (+ pump desk if cheap); **not** full site migration |
| Empty states | Council Weighing card pattern; never cascade “Could not load” without retry |
| Mind map | **Collapse below 480px** this wave; recolor later |
| Accuracy / scoring | **Out of scope** until H2 GO |

---

## PR queue (execute in order)

One PR → merge → babysit → next. Bundles already agreed.

```text
Wave 1 — Now
  PR1  Slice 4 combined effectiveness          (Lane A)
  PR2  SS-TG V5 visual                          (Lane B)
  PR3  Listener reconnect + empty-state kit     (Lane B + A UX)
  PR4  Topic chips v1                           (Lane B)
  PR5  Pump hero D+C-lite + desk atmosphere     (Lane B)
  PR6  Sticky spine + status rail               (Lane B)

Wave 2 — Same phase, after Wave 1 green
  PR7  Evidence sub-panels (council / learning) (Lane B)
  PR8  /pump full desk parity                   (Lane B)
  PR9  Mind map mobile collapse                 (Lane B)
  PR10 Living Focus CTA button polish           (Lane B)

Reactive (only if needed)
  PR-R Slice 5 SS-TG 390px fixes                (after H1 fails)

Checkpoint
  2026-08-04  H2 soak review + combined_angles block

Wave 3 — GATED on H2 GO
  PR11 Slice 7a accuracy measurement dashboard
  PR12 Optional: combined weight tune (if graded_n ≥ 20)
  PR13+ Slice 7b/7c weight audit / capped experiments (separate PRs)
```

---

## PR1 — Slice 4 combined effectiveness

**Branch:** `cursor/slice4-combined-effectiveness-6063`  
**Lock update:** `combined-angles-lock.md`

### Goal
Answer “does Combined beat Next up / Peers?” without changing weights or pump UI.

### Work

| Piece | Files |
|-------|-------|
| Grade / summarize ledger | `internal/pump/combined_ledger.py` — extend `ledger_stats()` (or `effectiveness_report()`) |
| Ops evidence field | `internal/ops/evidence.py` → `combined_angles` on `GET /api/ops/evidence` |
| Soak snapshot | `scripts/soak_review_snapshot.sh` — print combined block |
| Tests | `tests/test_combined_ledger_stats.py` (empty + graded fixtures) |

### Payload shape

```json
"combined_angles": {
  "calls": 0,
  "graded": 0,
  "pending": 0,
  "combined_hit_rate": null,
  "next_up_hit_rate": null,
  "peer_hit_rate": null,
  "ready": false,
  "weights": {"timing": 0.7, "peer": 0.3},
  "note": "experimental — do not tune until graded_n ≥ 20"
}
```

### AC
- [ ] Honest empty (`ready: false`) with zero graded calls  
- [ ] No weight / UI changes on pump desk  
- [ ] Soak script includes block; exit 0  
- [ ] Babysit green  

---

## PR2 — SS-TG V5 visual (desk only)

**Branch:** `cursor/ss-tg-visual-v5-prod-6063`  
**Ref:** `docs/mockups/telegram-pulse-visual-v5.html`

### Work

| Piece | Files |
|-------|-------|
| Fontshare Cabinet Grotesk + Chillax | `templates/partials/premium/message_intel_feed.html` |
| Mesh / glass / tinted panels | `static/css/council_first.css` scoped `.message-intel--v2` |
| Crown / champion / proof polish | same CSS (+ light JS class hooks if needed) |

### Non-goals
Sitewide palette rewrite · pump desk (PR5) · feed logic changes

### AC
- [ ] 390px: brand + pulse readable; no layout break  
- [ ] Fonts load; fallbacks to existing stack  
- [ ] Crowns / champions / feed still hydrate  
- [ ] Informal screenshot vs V5 mockup  

---

## PR3 — Listener reconnect + empty-state kit

**Branch:** `cursor/ss-tg-listener-empty-kit-6063`

### Listener

| Piece | Files |
|-------|-------|
| Backoff entity resolve; stop EOF spin | `message_intel/telegram_listener.py` |
| Session audit (file vs string) | `internal/message_intel/session.py` |
| Status: Live / Archive / Reconnecting | `static/js/message_intel_feed.js` + status rail |
| Optional reconnect endpoint | only if `WRITE_API_TOKEN` — else skip |

**Human ops note in PR:** `AuthKeyDuplicatedError` → rotate `TELEGRAM_SESSION_STRING` on worker.

### Empty-state kit

| Piece | Files |
|-------|-------|
| Shared `.desk-empty` / `.desk-error` | `static/css/council_first.css` |
| Apply to trending, champions, crowns, feed, paper portfolio | `message_intel_feed.js`, `cockpit_hydrate.js` |
| Copy: quiet vs error vs retry | same |

### AC
- [ ] No cascade of raw “Could not load” without retry/calm empty  
- [ ] Status rail never shows Live + stale simultaneously  
- [ ] `/api/message-intel/status` still truthful  

---

## PR4 — Topic chips v1

**Branch:** `cursor/ss-tg-topic-chips-v1-6063`

### Work

| Piece | Files |
|-------|-------|
| `classify_message_topics(text) -> list[str]` | `message_intel/nlp_engine.py` or `internal/message_intel/topic_tags.py` |
| Enrich on read (no DB migration) | `internal/message_intel/engine.py` |
| Render chips + optional filter | `message_intel_feed.js` + CSS |

### Starter tags
`validator` · `emissions` · `alpha` · `partnership` · `market`

### Non-goals
LLM · multi-language · council steering from tags

### AC
- [ ] Chips on ≥1 fixture message in test  
- [ ] Feed filter optional; All still works  
- [ ] No hit-rate / grading change  

---

## PR5 — Pump hero D+C-lite + desk atmosphere

**Branch:** `cursor/pump-hero-visual-dc-lite-6063`

### Work

| Piece | Files |
|-------|-------|
| Fill `pds-hero__visual`: phase mesh (D) + arc when `progress_series` ≥2 (C-lite) | `static/js/cockpit_hydrate.js`, `templates/partials/premium/pump_alert_scan.html` |
| Phase-tinted `pds-atmosphere` + ladder breathing room | scan CSS in template / `council_first.css` |
| Do not duplicate bar sparkline as a second chart | visual = ambient only |

### AC
- [ ] Cold hero (no series) still looks intentional  
- [ ] Warm hero shows soft arc; bar sparkline unchanged  
- [ ] Combined · experimental copy untouched  
- [ ] Preview `/preview/pump-desk-polish` OK  

---

## PR6 — Sticky spine + status rail

**Branch:** `cursor/visual-sticky-spine-6063`

### Work

| Piece | Files |
|-------|-------|
| Sticky COUNCIL / WEIGHING / LEAD / FOCUS / PROOF on scroll | `templates/partials/premium/header.html` + CSS |
| Status line ≥11px @390px; truncate + title tooltip | freshness / ops badge row |

### AC
- [ ] Spine usable after scroll past hero @390px  
- [ ] No overlap with Live/freshness pills  
- [ ] Desktop unchanged or improved  

---

## PR7 — Evidence sub-panels

**Branch:** `cursor/visual-evidence-panels-6063`

### Work
Tinted callout strips for Telegram proof hit-rate, council accuracy, resolver %, “what the loop learned” — reuse SS-TG subsection bar language; no new APIs.

### AC
- [ ] Key stats scannable in one glance @390px  
- [ ] Quiet when data missing (desk-empty kit)  

---

## PR8 — `/pump` full desk parity

**Branch:** `cursor/pump-full-desk-visual-parity-6063`

### Work
Port polish / atmosphere / hero visual hooks from scan compact to `pump_alert.html` + `templates/pump.html`.

### AC
- [ ] `/pump` matches home lead aesthetic  
- [ ] Full desk still loads; contract OK  

---

## PR9 — Mind map mobile collapse

**Branch:** `cursor/mindmap-mobile-collapse-6063`

### Work
Below 480px: hide interactive graph → “Open mind map” expands full-width (or link). No rainbow recolor this PR.

### AC
- [ ] Homepage @390px no overlapping unreadable nodes by default  
- [ ] Expand still works  

---

## PR10 — Living Focus CTA polish

**Branch:** `cursor/living-focus-cta-polish-6063`

### Work
COPY / DOWNLOAD / Open full letter — primary/secondary styles consistent with home CTAs; remove “disabled grey” look when functional.

### AC
- [ ] Buttons look actionable when handlers exist  
- [ ] Empty pick state still honest  

---

## PR-R — Slice 5 SS-TG 390px (reactive)

**Gate:** Human H1 fail list only.  
**Branch:** `cursor/finish-slice5-ss-tg-390px-6063`  
Fix listed AC failures; run `scripts/g0_phone_qa.sh`.

---

## Aug 4 checkpoint (H2)

```bash
./scripts/soak_review_snapshot.sh | jq .
curl -fsS https://subnet-dashboard.fly.dev/api/ops/evidence | jq '.combined_angles'
```

| Outcome | Next |
|---------|------|
| **GO** | Wave 3 — PR11 Slice 7a |
| **HOLD** | Fix soak issues; extend monitor; no accuracy experiments |
| **Tune Combined** | Only if GO **and** `graded_n ≥ 20` → PR12 |

---

## Wave 3 — GATED (H2 GO)

### PR11 — Slice 7a accuracy measurement
Read-only 7d/30d by expert/regime artifact + ops surface. Lock: create `accuracy-lift-lock.md`.

### PR12 — Combined weight tune (optional)
Only if evidence shows Combined under/over-performing vs next_up/peer with `graded_n ≥ 20`. One hypothesis per PR.

### PR13+ — Slice 7b / 7c
Weight audit (online path) · capped scoring experiments — **separate PRs**, never bundled with visual work.

---

## Explicitly out of scope (this wave)

- Sitewide font migration / full rebrand  
- Council stage hero redesign (gameplan S1)  
- Mind map palette redesign (beyond collapse)  
- Accuracy / scoring before H2 GO  
- Chutes / live LLM chat  
- Custom domain / CDN  
- Two-agent parallel mode  

---

## Conflict surface

| File | Rule |
|------|------|
| `server.py` | One PR at a time if touching routes |
| `tests/test_endpoint_contract.py` | Add route when adding endpoint |
| `static/css/council_first.css` | Rebase if PR2/3/5/7 overlap |
| `data/*.json` | Never commit local churn |

---

## Definition of done (wave complete)

Wave 1–2 **DONE** when:

1. All PR1–PR10 merged (or consciously dropped with board note)  
2. Babysit C + learning loop green after last merge  
3. Prod curl: `combined_angles` present; reaction crowns + topic chips + hero visual visible  
4. Empty-state kit on Telegram + learning error paths  
5. Sticky spine works @390px  
6. Board + Ditto STATUS updated; this plan marked WAVE COMPLETE  

Wave 3 **DONE** when H2 GO path finishes PR11 (+ optional PR12) and board Phase 4 status updates.

---

## Approval templates

```text
EXECUTE pre-aug4-polish-plan — start PR1
```

```text
PR N APPROVED — merge verified, babysit green. Proceed to PR N+1.
```

```text
PR N HOLD — [reason]. Fix before next.
```

```text
Phase 4 UNGATED — day-7 soak GO. Proceed to PR11.
```

---

## Quick reference — file ownership by PR

| PR | Primary touch |
|----|----------------|
| 1 | `combined_ledger.py`, `evidence.py`, soak script |
| 2 | `message_intel_feed.html`, `council_first.css` (mi--v2) |
| 3 | `telegram_listener.py`, `message_intel_feed.js`, empty CSS |
| 4 | `nlp_engine` / topic_tags, `engine.py`, feed JS |
| 5 | `cockpit_hydrate.js`, `pump_alert_scan.html` |
| 6 | `header.html`, spine/status CSS |
| 7 | learning/proof partials + CSS |
| 8 | `pump_alert.html`, `pump.html` |
| 9 | mindmap CSS/JS |
| 10 | Living Focus partials + CTA CSS |
