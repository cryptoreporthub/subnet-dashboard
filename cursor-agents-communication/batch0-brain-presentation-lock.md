# Batch 0 LOCK — Brain presentation architecture

**Status:** DRAFT for human sign-off (2026-07-19)  
**Batch:** 0 — Brain / mindmap / learning loop presentation  
**Priority:** Rank 1 moat (see `docs/presentation-audit.md`)  
**Viewport:** 390px primary  
**Evidence:** SSR inventory + `/preview/k3-hold` screenshots (`batch0-k3-hold-hero.png`, `batch0-k3-track-record.png`)  
**Out of scope:** Engine/logic, Daily Call hero stack redesign, Weighing/Pump polish (Rank 3), Council/judges Batch 1

---

## Verdict (one line)

The brain **exists in pieces** but **does not read as one living loop**. Tier‑1 scrolls past competing “today’s narrative” sections that mostly show loading zombies, while the real graded proof is a quiet whisper + a collapsed peel + a buried Pro drawer.

---

## Scorecard (current Batch 0)

| Axis | Score | Note |
|------|-------|------|
| 5-second clarity | 4 | Call is clear on hero |
| Hierarchy | 2 | Brain proof quiet; Living Focus / Brain letter compete |
| Voice | 3 | Track record footnote OK; “brain UI gate” / warming copy weak |
| Calm authority | 4 | HOLD hero calm |
| Motion & feedback | 2 | Home hydrate → loading zombies on LF / letter / what’s working |
| Honest-empty | 2 | Multiple “Loading…” shells feel broken |
| **Learning presence** | **2** | Moat not obvious as a spine — buried / duplicated |

**Gate:** Learning presence ≥4 required to close Batch 0.

---

## FINDINGS (ranked)

1. **Three “today’s brain” surfaces compete after the call**  
   Living Focus + Brain letter + dossier peels all narrate the same day. K3 docs said LF / brain letter were “absorbed by dossier” — they still ship as full Tier‑1 sections with loading empty states.

2. **Learning peel is stats-only; weight-nudge step is hidden**  
   `#k3-layer-learning` shows graded n + accuracy (good) but `#k3-lifecycle-learning` is `hidden`. The *loop* (call → grade → weight update) never appears on the default path.

3. **Cause chain rendered three times**  
   Outcome peel `#k3-lifecycle-outcome` · Pro `#section-story-path` · Brain letter “How we got here” — same story-path shape, three UIs.

4. **Proof band is a landfill of digests**  
   What’s working → Paper portfolio → Weekly letter → Daily recap — four sequential “prove it” sections, all loading-first. No single composed proof strip.

5. **Mindmap graph / trail live in Market drawer**  
   Correct demotion for interactive graph; Living Focus trail teaser linking to Market is fine. Do **not** promote the empty Interactive Graph to Tier‑1.

6. **Trust whisper is the strongest brain beat above the fold**  
   `443 graded · 31.4% dir.` works. Trust banner below claim repeats similar info — OK as peel-adjacent, but don’t add a third accuracy block.

---

## IA LOCK (Tier placement)

### Tier‑1 — always in the council story (spine attachments)

| Surface | Decision |
|---------|----------|
| Daily Call dossier | **Keep** — claim leads |
| Trust whisper (`443 graded · x% dir.`) | **Keep** — primary Learning presence above fold |
| Outcome peel lifecycle (≤4 steps) | **Keep** — spine beat for *this* call |
| Track record peel | **Keep + enrich** — show last graded beat + one weight-nudge line (unhide learning step when data exists) |
| Weighing Room / Pump | Unchanged this batch (ribs; Rank 3 later) |

### Tier‑2 — one “Proof” band (accountability)

Compose a single band after Pump (or after Weighing — keep current order relative to call):

| Surface | Decision |
|---------|----------|
| What’s working | **Keep** as lead chip strip of the proof band |
| Paper portfolio | **Keep** inside proof band |
| Story strip (recent right/wrong) | **Promote from Pro** into proof band (compact horizontal / list) — this is the visible graded timeline |
| Weekly letter + Daily recap | **Demote into a single “Letters” `<details>`** under the proof band (or into Pro) — stop three digests in a row |

### Tier‑3 — Pro / Market (depth)

| Surface | Decision |
|---------|----------|
| Living Focus | **Demote to Pro** (or collapse into Outcome/Track peels). Stops competing with dossier. |
| Brain letter | **Demote to Letters `<details>` or Pro** — dossier already owns today’s narrative |
| Story path (full chain UI) | **Stay Pro** as deep view; Tier‑1 keeps the slim Outcome lifecycle only |
| Council / Judges / KPI / Backtest | Stay Pro (Batch 1 may promote judge disagreement cues into peels) |
| Mindmap graph + Trail | Stay Market drawer |

### Narrative LOCK (trader sentence)

> **“Here’s what we called, how it grades, and how the council changes when we’re wrong.”**

Every Tier‑1/2 brain surface must serve that sentence. If it doesn’t, demote or delete from main scroll.

### Handoff rules (ribs → spine)

- **Weighing Room** footer may keep “These may become tomorrow’s call” — add whisper only if space: “Graded when the daily call locks.”  
- **Pump** stays predictive heat — **no** learning stats on pump cards.  
- **Track record peel** is the only place for accuracy % + weight nudge on the dossier.  
- **Proof band** owns multi-call history (story strip + what’s working). Do not restate full accuracy block there if whisper already showed it — show *what improved* / *which signals worked*.

---

## COPY LOCK

| Where | Before → After |
|-------|----------------|
| Track record peel empty lifecycle | Unhide when step exists; else one line: `After resolve, judge weights nudge from this window.` (not “warming up”) |
| Living Focus (until demoted) | If still visible briefly: never “Loading focus from council…” as final — prefer `Focus builds after the first council tick.` |
| Brain letter loading | `Today's letter appears after graded history is ready.` |
| What’s working empty | Keep honest: `Not enough graded picks yet to rank price signals.` |
| KPI “brain UI gate” | Rename to trader English: `Integrity` or `Resolver integrity` — never “brain UI gate” |
| Story path empty (Pro) | `No audited pick yet — the chain fills when today's call is live.` |

Banned in Tier‑1 brain copy: `warming up`, `brain UI gate`, `§16`, internal slice jargon.

---

## VISUAL LOCK (minimal — after IA)

1. Proof band shares section-label pattern with Weighing (`Council is weighing` style) — e.g. **`The brain keeps score`** or **`What the loop learned`**.  
2. Story strip in Tier‑2: compact right/wrong rows — not a second hero.  
3. Track record peel: stats row stays; add one **last HIT/MISS + weight delta** line when available (reuse living-focus learn payload shape if present).  
4. No new neon / no new card chrome — reuse dossier + weighing tokens.

---

## IMPLEMENTATION SLICES (Composer, after sign-off)

Ordered for smallest safe diffs:

### B0-a — Demote competitors (IA)
1. Move `living_focus.html` include into `#pro-cockpit` (after story_path or before judges).  
2. Move `brain_letter.html` into a Letters `<details>` with weekly + daily, **or** into Pro. Prefer Letters details under proof band.  
3. Keep `#section-*` ids for hydrate/onboarding; update onboarding tour if it targets Living Focus.  
4. Tests: `test_phase_h_ui` / contract — sections still present; assert order: daily-pick → … → whats-working before letters details.

### B0-b — Promote story strip into proof band
1. Include `story_strip.html` on main scroll immediately above or below `#section-whats-working`.  
2. Remove duplicate include from Pro **or** leave a “Open full strip” link in Pro that scrolls to it (prefer single include on main).  
3. Soften strip chrome to match proof band (section-label + title).

### B0-c — Track record peel: show the loop
1. Unhide `#k3-lifecycle-learning` when learning step data exists.  
2. When no step: show static one-liner from COPY LOCK (not hidden empty).  
3. Optional: one “Last graded” HIT/MISS line from existing trust/learning payloads — no new API if data already on page.

### B0-d — Letters collapse + copy hygiene
1. Wrap weekly + daily (+ brain letter if not Pro) in `<details class="letters-drawer">`.  
2. Rename KPI sub “brain UI gate” → `Resolver integrity`.  
3. Replace remaining Tier‑1 “warming up” strings listed in COPY LOCK.

### Explicitly NOT in Batch 0
- Redesign Daily Call claim stack  
- Weighing Room / Pump visual polish  
- Interactive mindmap promotion  
- New `/api/lifecycle`  
- Batch 1 judge theater redesign  

---

## Preview / QA

| Check | Route |
|-------|-------|
| Hero + trust whisper + peels | `/preview/k3-hold` |
| Proof band order + letters drawer | `/` 390px after hydrate |
| Pro still has story path + demoted LF | `/` → open Pro cockpit |
| No loading zombie as final empty | Force empty API / honest-empty copy |

Phone QA checklist: Learning presence ≥4 — trader can answer “does this thing learn?” without opening Pro.

---

## Sign-off

- [ ] Human approves IA LOCK (demote LF + brain letter; promote story strip; letters drawer)  
- [ ] Human approves COPY LOCK  
- [ ] Human approves slice order B0-a → B0-d  
- [ ] Then Composer implements on branch `cursor/batch0-brain-presentation-*-e7f9`

**Suggested reply to unlock build:** `LOCK signed — implement B0-a through B0-d`
