# Batch 0 — FINAL merged implementation plan

**Status:** FINAL PLAN — awaiting human execute (no product code yet)  
**Sources merged:** Grok B0 plan (`batch0-implementation-plan.md`) × Ditto Visual Update Audit (VA-00…VA-14)  
**LOCK canon:** `batch0-brain-presentation-lock.md` v2.1 (still binds)  
**When executing:** branch `cursor/batch0-brain-presentation-impl-e7f9` off latest `main`

---

## Comparison (same / better / revise)

### Same (both agree — keep)

| Theme | Grok B0 | Ditto VA | Final |
|-------|---------|----------|-------|
| Keep LF + Brain letter; elevate, don’t demote | ✅ | ✅ (VA-03/04) | Keep |
| Kill “warming up” / loading zombies | B0-d | VA-08 (stronger) | Adopt Ditto discipline |
| Collapse weekly/daily letters | B0-c | VA-10 | Keep |
| Don’t polish empty mindmap graph | LOCK guard | VA-09 | Keep — hide or real trail, never empty canvas |
| Dual judge systems must be labeled | LOCK | VA-14 | Keep |
| Weight-nudge / “watch us update” visible | B0-a/c | VA-07 | Keep |
| What’s working = loop proof | proof band | VA-06 | Keep |
| Phone / 390px matters | B0-d | VA-12 | Keep |
| Scope: small, honest, alive — not 20 polished empties | LOCK | bottom line | Keep |

### Where Ditto is better (adopt)

| Ditto item | Why better | How we absorb |
|------------|------------|---------------|
| **VA-00 / Phase 1 reconnect mindset** | Correct product diagnosis: promised-but-dead surfaces spend trust | Add **B0-0 gate** before polish: Tier‑1 surfaces must show data or dignified quiet within ~5s |
| **VA-02 unified degraded mode** | One honest offline > ten spinners | Client: one probe / shared hydrate failure → Quiet card, not per-widget zombie |
| **VA-05 score as designed proof** | 33%/454 is the honesty weapon; whisper is too quiet | Promote trust score into proof-band hero (still RF-2: not on LF bars) |
| **VA-04 “real > live” SSR letter** | Ship letter from on-disk graded data even if hydrate is slow | Prefer SSR/file-backed letter content; Outlook still added |
| **VA-08 Live / Quiet / Building** | Better empty taxonomy than ad-hoc copy | Replace warming-up with those three states on B0 surfaces |
| **VA-13 homepage focus** | Warehouse problem is real | Don’t delete Weighing/Pump this batch, but **first viewport = call + score + one living surface**; rest below |

### Where Grok B0 is better (keep)

| Grok item | Why better than Ditto alone |
|-----------|----------------------------|
| **§27 four-beat Living Focus** | Precise product already locked — Ditto VA-03 is right about “alive” but thinner on Focus→Contest→Prove it→Watch us update |
| **Outlook / Next sentence** | Ditto missed the forward-pick beat you asked for |
| **File-level ACs + test list** | Executable; VA list is audit severity, not build tickets |
| **Concept guardrails (Ditto-verified)** | Prevents graph-as-paradigm / demote-LF drift |
| **Don’t redesign Daily Call hero** | VA-11 risks reopening K3-7 LOCK; absorb as copy clarity only, not stack redesign |
| **Weighing/Pump stay ribs** | VA-13 “homepage = 3 things only” is too aggressive for this batch |

### Where Ditto overstated (correct before sequencing)

**Live re-check (2026-07-20):** Locally, key brain APIs return **200** (`/api/letter/brain`, `/api/market-drivers`, `/api/daily-pick`, `/api/mindmap/trail`, `/api/learning/stats`, `/api/judges/{n}`, `/api/calibration/status`, etc.). Live fly.dev often **times out** under load — not a clean “five of six are 422 / routers missing” story.

**Revised VA-00:** The moat failure mode is **perceived death** (SSR skeletons + slow/failed hydrate = forever Loading), not “backend missing.” Fix = **SSR real content + honest Quiet + hydrate that patches without zombies** — not a blind “resurrect every 422” rebuild.

---

## Final sequencing

```text
B0-0  Reconnect perception (Tier-1 only)     ← Ditto Phase 1, corrected
  → B0-a  Living Focus elevate (§27)         ← Grok + VA-03/07
  → B0-b  Brain letter + Outlook + SSR       ← Grok + VA-04
  → B0-c  Proof band (score hero + strip + letters)  ← Grok B0-c + VA-05/06/10
  → B0-d  Empty-state taxonomy + tour + 390px QA     ← Grok B0-d + VA-08/12/14
```

**Hard gate:** Do not ship B0-a…d polish if Tier‑1 surfaces still show eternal Loading after 5s on prod phone. B0-0 must land first (same PR OK if ordered).

---

## B0-0 — Reconnect perception (NEW, from Ditto, corrected)

### Intent
No Tier‑1 surface spends trust with infinite Loading. Real data or Quiet.

### Scope (Tier‑1 only this batch)
Living Focus · Brain letter · What’s working · Track record / trust score · Story strip (once promoted)

### Work
1. Inventory hydrate deps for those surfaces; ensure SSR shows last-known / file-backed content when APIs are slow  
2. Shared failure path: after timeout, replace spinner with **Quiet** (`Last updated …` / `No graded beat yet`) — never “warming up”  
3. Optional: one lightweight `dataHealth` for these endpoints only (not whole warehouse)  
4. Mindmap empty graph: **hide from homepage prominence** or show trail list — no empty canvas (VA-09) — Market drawer OK  

### AC
- [ ] After 5s on phone, zero eternal Loading on LF / Brain letter / What’s working  
- [ ] Quiet states dated when possible  
- [ ] No claim that “all APIs 422” — fix perception + slow hydrate  

### Do NOT
- Rebuild all Market drawer endpoints this batch  
- Remove LF/letter  

---

## B0-a — Living Focus (§27 + alive)

### Intent
Focus → Contest → Prove it → Watch us update. Real contention or timestamped last-real — never infinite loader.

### Files
`living_focus.html`, `living_focus.js`, minimal CSS  

### Work
1. Sub: `Focus · Contest · Prove it · Watch us update`  
2. Render order: contention → **last learn** → who-drives → chips → switcher → CTA  
3. Soften thesis/FLIP overlap  
4. If judges fail: Quiet with last snapshot if any, else honest empty — no spinner forever (VA-03)  
5. Weight-nudge plain English under who-drives when trail has delta (VA-07)  
6. RF-2: no global win-rate on LF  

### AC
Same as prior B0-a + no eternal Loading  

---

## B0-b — Brain letter + Outlook (+ SSR)

### Intent
Dated briefing from real graded memory; Outlook forward sentence; learning leads.

### Files
`brain_letter.py`, `brain_letter.js`, `brain_letter.html`, export path  

### Work
1. SSR/meta: `Morning brief · graded memory`  
2. Block order: What changed → Today (short + link) → **Next/Outlook** → Integrity  
3. Outlook rules from LOCK (timed to `resolves_in`, ≤140 chars)  
4. Drop story-path block from letter UI  
5. Prefer file/SSR content so letter isn’t hydrate-only (VA-04)  
6. Kill audit-gate copy  

### AC
Same as prior B0-b + letter visible without waiting on flaky hydrate  

---

## B0-c — Proof band (score hero + strip + letters)

### Intent
Honesty weapon + loop timeline + no digest landfill.

### Files
`premium_cockpit.html`, `council_stage.html` (Track record), `story_strip.html`, trust/proof chrome  

### Work
1. **Proof band label:** e.g. `What the loop learned`  
2. **VA-05:** Promote graded score into designed proof-band hero (big % + n graded + “published, not curated”) — first-ish mobile scroll after call, not only grey whisper (whisper may stay above-fold lightly)  
3. What’s working chips stay; ensure Quiet if drivers slow (VA-06)  
4. Promote story strip onto main scroll (single include); remove Pro duplicate  
5. Letters `<details>` for weekly + daily  
6. Track record peel: weight-nudge line  

### Scroll
```text
Daily Call (+ light trust whisper OK)
  → Weighing / Pump (ribs — keep this batch)
  → Living Focus
  → Brain letter
  → Proof band: SCORE HERO + What’s working + Story strip + Paper
  → Letters <details>
  → Pro / Market
```

### AC
Prior B0-c + score readable without hunting; one story-strip ID  

### Revise vs Ditto VA-13
Do **not** strip Weighing/Pump from homepage this batch. Thumb-first = score + call + LF/letter priority; ribs stay below fold.

### Revise vs Ditto VA-11
No Daily Call stack redesign. Optional one plain-English “so what” line only if it fits existing brief fields — not a new hero architecture.

---

## B0-d — Empty taxonomy + dual-judge clarity + QA

### Intent
Trust hygiene + teach the model + phone sign-off.

### Work
1. **VA-08:** On B0 surfaces only — replace warming-up with `Live` / `Quiet` / `Building`  
2. KPI: `brain UI gate` → `Resolver integrity`  
3. **VA-14:** One short label pair everywhere we show both systems: `Judges (Oracle/Echo/Pulse)` vs `Council weights (soul map)`  
4. Onboarding: Call → LF four-beat → Letter (+ Outlook)  
5. Phone QA checklist (below)  

### Phone QA (390px)
1. Call clear in first viewport  
2. Score / honesty visible without opening Pro  
3. LF: contention + last learn (or Quiet) — no eternal Loading  
4. Letter: Outlook visible; feels forward  
5. Proof band: what’s working + strip  
6. Letters collapsed; mindmap not an empty hero  
7. 60s: know what to watch, that it learns, what it expects next  

---

## Explicitly do NOT touch

- Remove Living Focus or Brain letter  
- Daily Call K3-7 hero redesign  
- Weighing / Pump polish / removal  
- Empty mindmap graph as primary paradigm  
- New `/api/lifecycle` / fourth weight path  
- Full Market drawer rewrite  
- Commit `data/*.json`  

---

## Risks

| Risk | Mitigation |
|------|------------|
| Chasing phantom 422s | Verify with TestClient + timed prod curls; fix hydrate/SSR first |
| Score hero reads as “bad product” | Always pair % with n + “published, not curated” |
| Scope balloon | B0-0 Tier‑1 only; warehouse demotion deferred |
| Duplicate story-strip IDs | Grep; single include |

---

## Definition of Done

- [ ] B0-0: no eternal Loading on Tier‑1 brain surfaces @390px prod  
- [ ] B0-a…d AC green  
- [ ] LOCK v2.1 concept guardrails intact  
- [ ] Targeted pytest green  
- [ ] Learning presence feels ≥4 on phone checklist  

---

## Human replies

```text
Final plan approved — do not execute yet
```

```text
Execute final B0 plan (B0-0 through B0-d)
```
