# Post-stability — Automated build plan (Build button queue)

**Status:** ACTIVE — hit **Build** in Cursor chat to run the next slice  
**Updated:** 2026-07-25  
**Baseline:** `main` = `c75e7ed` (#469 pump hero merged)  
**Strategy doc:** `post-stability-sprint-plan.md` (context only — **this file is the queue**)  
**Batch 0 detail:** `batch0-final-merged-plan.md` + `batch0-brain-presentation-lock.md` v2.1

---

## Agent prompt (Build / cloud agent — one slice per run)

```
POST-STABILITY BUILD AUTOMATION:
1. Read STATUS.md → this file → active slice AC only (do not re-litigate shipped work).
2. Checkout latest origin/main. Branch: cursor/post-stab-<slug>-d2cd
3. Implement ONE queue row. Tests: pytest tests/test_endpoint_contract.py -q (+ slice tests).
4. Commit · push · open/update PR (draft=false when ready).
5. Wait for smoke CI green · merge to main · delete branch.
6. Post-merge prod curl (see Verify block below). Update queue row ✅ + STATUS.md + Ditto save_memory.
7. Auto-continue to NEXT row unless slice is marked ⏸ PAUSE (human gate).
8. No data/*.json commits · ponytail minimal diff · Composer 2.5 default.
9. Do NOT touch Agent B owned paths (whales/ruggers/indicators/oracle/analytics).
```

---

## Queue (sequential · unattended except ⏸)

| # | Slice | Branch slug | State |
|---|-------|-------------|-------|
| **P0** | Pump desk flagship hero (#469) | `pump-desk-flagship-d2cd` | ✅ merged `c75e7ed` |
| **A0** | Prod curl verify (pump hero payload) | — | ✅ passed 2026-07-25 |
| **A-HUMAN** | 390px sign-off + optional screenshots | — | ⏸ **PAUSE** — user checking |
| **A1** | Wave A gate green on prod | `wave-a-gate-fix-d2cd` | pending (only if A0/A-HUMAN fail) |
| **B0-a** | Living Focus §27 four-beat | `b0-a-living-focus-d2cd` | ⏳ next after A-HUMAN pass |
| **B0-b** | Brain letter + Outlook SSR | `b0-b-brain-letter-d2cd` | pending |
| **B0-c** | Proof band score hero + strip | `b0-c-proof-band-d2cd` | pending |
| **B0-d** | Live/Quiet/Building + 390px QA | `b0-d-empty-taxonomy-d2cd` | pending |
| **C1** | P5 founder/owner chip | `p5-founder-chip-d2cd` | pending |
| **C2** | Social conviction (#455 rebase) | `social-conviction-d2cd` | pending · optional |
| **D1** | Chat fast-path completion | `chat-fast-path-d2cd` | pending |
| **E1** | Subnet integrations API | `subnet-integrations-api-d2cd` | pending |
| **E2** | Subnet integrations UI | `subnet-integrations-ui-d2cd` | pending |
| **E3** | Macro overlay + llm-cost | `subnet-macro-overlay-d2cd` | pending · optional |
| **F1** | STATUS + stale PR hygiene | `housekeeping-d2cd` | pending · parallel OK |

**Out of scope:** Fly `scale worker=1` (human ops) · H1 hour-watch (after B0-d + G0) · algorithm rewrites

---

## ⏸ A-HUMAN — User gate (STOP until pass message)

**User is checking pump hero on phone.** Agent must **not** start B0-a until user sends pass (screenshots optional).

**User checks:**
- Featured Call loads
- Pump desk hero: **Flow** / **Confirm** / **Approach** chart above Distance
- One horizon path without Pro scroll @390px

**On user pass:** tick A-HUMAN ✅ in this table · record in Ditto · start **B0-a**.  
**On user fail:** fix on `cursor/pump-desk-hotfix-d2cd` · re-run A0 curl · re-pause for human.

---

## Verify block (run after every merge)

```bash
BASE=https://subnet-dashboard.fly.dev

# Health
curl -fsS --max-time 15 "$BASE/health"

# Pump desk hero contract
curl -fsS --max-time 25 "$BASE/api/pump-alerts" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('status') != 'timeout', d
hero=d.get('hero') or {}
assert d.get('desk') is True
if hero:
    assert 'progress_series' in hero, hero.keys()
    assert 'confirm_pct' in hero
    assert 'formation_pct' in hero
    ps=hero.get('progress_series') or []
    assert len(ps) >= 2, ps
print('pump-hero OK', hero.get('name'), 'progress_tail', (hero.get('progress_series') or [])[-3:])
"

# Full gate (local + prod)
./scripts/wave_a_gate.sh
```

**Home HTML spot-check:** `pump-progress`, `data-progress`, `Flow`, `Confirm`, `Approach` present; no `data-corr-form`.

---

## B0-a — Living Focus (next build slice)

**Canon:** `batch0-final-merged-plan.md` § B0-a · K3-7 LOCK (no hero redesign)

**AC:**
- [ ] Sub: `Focus · Contest · Prove it · Watch us update`
- [ ] Render order: contention → last learn → who-drives → chips → switcher → CTA
- [ ] Judges fail → Quiet with last snapshot, not eternal Loading
- [ ] Weight-nudge plain English when trail has delta
- [ ] RF-2: no global win-rate on LF bars
- [ ] `pytest tests/test_endpoint_contract.py -q` green
- [ ] A0 curl block green after merge

**Files:** `templates/partials/premium/living_focus.html`, `static/js/living_focus.js`, `static/css/council_first.css`

---

## B0-b — Brain letter + Outlook

**AC:**
- [ ] SSR letter from file-backed graded data (not hydrate-only)
- [ ] Outlook/Next sentence ≤140 chars, timed to `resolves_in`
- [ ] Block order: What changed → Today → Outlook → Integrity
- [ ] No audit-gate copy in letter UI

**Files:** `internal/letter/brain_letter.py`, `templates/partials/premium/brain_letter.html`, `static/js/brain_letter.js`

---

## B0-c — Proof band

**AC:**
- [ ] Graded score hero in proof band (big % + n graded)
- [ ] Story strip on main scroll (single include)
- [ ] Letters in `<details>`; What's working Quiet when slow

**Files:** `templates/partials/premium/premium_cockpit.html`, `council_stage.html`, story strip partials

---

## B0-d — Empty taxonomy + 390px

**AC:**
- [ ] Live / Quiet / Building (no "warming up" zombies)
- [ ] Dual-judge labels per LOCK
- [ ] `g0_phone_qa.sh` green · record G0 in `gameplan-pump-site-undeniable.md`

---

## C1 — P5 founder chip

**AC:**
- [ ] Chip on pump desk row when registry has owner; hidden when unknown
- [ ] 390px: chip does not break compact row

---

## Contract (every slice)

1. Branch `cursor/post-stab-<slug>-d2cd` off latest `main`
2. One PR per slice · merge when `smoke` CI passes
3. No `data/*.json` in commits
4. Update this queue row + `STATUS.md` on merge
5. **⏸ rows:** stop and report; do not auto-continue

## Token discipline

This file is the queue cache. Git diff is truth. Grok only on AC fail or ambiguous copy LOCK.
