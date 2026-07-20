# Batch 0 — Implementation plan (DO NOT EXECUTE YET)

**Status:** PLAN READY — awaiting human “execute”  
**LOCK:** `cursor-agents-communication/batch0-brain-presentation-lock.md` **v2.1**  
**Branch (docs):** `cursor/batch0-brain-presentation-lock-e7f9` / PR #378  
**When executing:** new branch `cursor/batch0-brain-presentation-impl-e7f9` off latest `main` (rebase if #378 merged)  
**Viewport:** 390px primary · presentation only · no new foundation APIs

---

## Goal

Make the brain read as one living loop on phone:

- **Living Focus** = §27 Focus → Contest → Prove it → Watch us update  
- **Brain letter** = briefing with **Outlook/Next** forward sentence  
- **Proof band** = What’s working + story strip + paper  
- **Track record peel** shows weight-nudge whisper  

Without demoting LF/letter, without polishing empty mindmap graph, without Daily Call hero redesign.

---

## Sequencing (strict)

```text
B0-a Living Focus
  → B0-b Brain letter (+ Outlook)
  → B0-c Track record + proof band IA
  → B0-d Copy hygiene + onboarding + phone QA
```

One PR preferred (all four slices) **or** stacked PRs per slice if CI noise — default **one PR** for coherence.

---

## B0-a — Living Focus product pass

### Intent
Elevate §27 Focus Object. Stop “second dossier” / eternal loading.

### Files
| File | Change |
|------|--------|
| `templates/partials/premium/living_focus.html` | Sub copy → `Focus · Contest · Prove it · Watch us update`. SSR empty → skeleton or `Focus opens when judges score this subnet.` — never leave “Loading focus from council…” as calm state |
| `static/js/living_focus.js` | Render order: header → **contention/judges** → **last learn** → who-drives → chips → switcher → CTA. Soften any thesis/FLIP restatement (action badge + name only) |
| `static/css/council_first.css` or `premium.css` | Minimal: skeleton bars; learn strip prominence — no new theme |
| `internal/preview/` + route (optional) | `/preview/k3-living-focus` fixture for 390px — **optional**; skip if time-box |

### APIs (read only — already wired)
`/api/daily-pick`, `/api/judges/{n}`, `/api/calibration/status`, `/api/mindmap/trail`, `/api/simivision`, prove-it / capsule as today

### AC
- [ ] Sub text matches §27 four-beat (or approved short form)  
- [ ] First meaningful content after hydrate = judge contention, not a call thesis paragraph  
- [ ] Last learn strip visible when trail has focus SN beat; honest-empty otherwise  
- [ ] No global accuracy/win-rate on LF (RF-2)  
- [ ] Section id `#section-living-focus` preserved  

### Tests
- Extend `tests/test_living_brain.py` or `test_home_habit_ui.py`: assert sub string + section present  
- Manual: `/?focus=` scrolls/focuses LF  

---

## B0-b — Brain letter product pass (+ Outlook)

### Intent
L11 briefing: learning leads; short call citation; required **Outlook**; drop duplicate story-path block.

### Files
| File | Change |
|------|--------|
| `internal/letter/brain_letter.py` | Add `outlook` (or `next`) string from stance + `resolves_in`/`horizon` + trigger gist. Reorder payload blocks. Drop or omit `story_path` from letter UI payload (Pro/Outcome keep chain) |
| `static/js/brain_letter.js` | Render: What changed → Today (short + link `#section-daily-pick`) → **Next/Outlook** → Integrity. Kill audit-gate HOLD copy |
| `templates/partials/premium/brain_letter.html` | Meta → `Morning brief · graded memory`. Empty → `Brief writes after the first graded windows land.` |
| Markdown export path in `brain_letter.py` / `letter_export.js` | Include Outlook in export |

### Outlook composition rules (from LOCK)
- ≤ ~140 chars, one sentence  
- Time from real `resolves_in` / horizon — never invent “tonight”  
- HOLD / LONG / quiet desk variants per LOCK examples  
- Must not restate full FLIP box or invent price targets  

### AC
- [ ] `/api/letter/brain` includes `outlook` (or nested under a clear key)  
- [ ] UI shows Outlook labeled `Next`  
- [ ] Block order matches LOCK  
- [ ] No “How we got here” story-path list in letter UI  
- [ ] Copy/download still work  
- [ ] HOLD copy has no “audit gate”  

### Tests
- `tests/test_brain_letter.py`: outlook present; no audit-gate string; order/keys  
- Optional markdown contains Outlook  

---

## B0-c — Track record peel + proof band

### Intent
Show the loop on dossier; compose proof band; stop digest landfill.

### Files
| File | Change |
|------|--------|
| `templates/partials/premium/council_stage.html` | `#k3-layer-learning`: unhide / always show weight-nudge one-liner when step exists; else `After resolve, judge weights nudge from this window.` |
| `templates/partials/premium_cockpit.html` | Move `story_strip.html` include into main scroll **adjacent to** `#section-whats-working` (above or below chips). **Single include** — remove from Pro drawer *or* leave Pro with scroll-link only (prefer single include on main) |
| `templates/partials/premium/story_strip.html` | Soften chrome to proof-band section-label pattern if needed (`What the loop learned` band context) |
| `templates/partials/premium_cockpit.html` | Wrap `weekly_letter.html` + `daily_recap.html` in `<details class="letters-drawer">` under proof band |
| `static/js/onboarding_tour.js` / hydrate | Fix any selectors if strip leaves Pro |

### Scroll target after B0-c
```text
… pump → Living Focus → Brain letter
  → What’s working + Story strip + Paper   (proof band)
  → Letters <details> (weekly + daily)
  → Pro (story path deep, etc.) → Market
```

### AC
- [ ] `#section-story-strip` appears on main scroll before Pro  
- [ ] Only one story-strip mount (no duplicate IDs)  
- [ ] Weekly + daily inside Letters details (collapsed by default)  
- [ ] Track record peel shows nudge line or honest static line  
- [ ] Contract / phase-h tests still find required section ids  

### Tests
- `tests/test_u2_story_strip.py`, `test_phase_h_ui.py`: order asserts `section-whats-working` / `section-story-strip` before `pro-cockpit`  
- Letters drawer present  

---

## B0-d — Copy hygiene + QA

### Intent
Kill Tier‑1 jargon zombies; teach tour; phone sign-off.

### Files
| File | Change |
|------|--------|
| `templates/partials/premium/kpi.html` | `brain UI gate` → `Resolver integrity` |
| LF / brain letter / Track record / story path empties | Replace remaining `warming up` / audit-gate on **these** surfaces only (don’t rewrite entire Market drawer) |
| `static/js/onboarding_tour.js` | Steps: Daily Call → Living Focus (four-beat) → Brain letter (briefing + Outlook) — keep short |
| Preview routes | Exercise `/preview/k3-hold` + home 390px checklist |

### AC
- [ ] No `brain UI gate` string in home HTML  
- [ ] Tour describes LF + letter jobs correctly  
- [ ] Phone checklist (below) passes  

### Phone QA checklist (390px)
1. Daily Call clear in first viewport  
2. Living Focus: contention + last learn readable without hunting  
3. Brain letter: Outlook visible; feels forward, not only past  
4. Proof band: what’s working + strip without opening Pro  
5. Letters drawer collapsed; Pro still has story path  
6. Anti-pattern: 60s — know what to watch, that the system learns, what it expects next  

---

## Explicitly do NOT touch

- Remove Living Focus or Brain letter  
- Daily Call claim stack redesign (HOLD/BUY hero LOCK stays)  
- Weighing Room / Pump polish  
- `#section-mindmap` graph as “the fix”  
- New `/api/lifecycle` or fourth weight path  
- Committing `data/*.json` / `.venv`  

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Duplicate `#section-story-strip` if Pro include left in | Grep after edit; single include |
| Brain letter pick file vs live `/api/daily-pick` diverge for Outlook clock | Prefer temporal fields from same enrichment used by dossier when available; else honest omit clock |
| LF learn strip empty on quiet resolver | Honest-empty copy — still counts as pass |
| Test suite pre-existing failures | Only require green on touched tests + `test_endpoint_contract.py` + LF/letter/strip tests |

---

## Definition of Done (Batch 0)

- [ ] LOCK v2.1 behaviors visible on home @ 390px  
- [ ] Learning presence self-score ≥4 on phone checklist  
- [ ] Targeted pytest green  
- [ ] PR opened; Ditto STATUS posted  
- [ ] No concept drift vs Ditto guardrails section in LOCK  

---

## Human gates

1. **Now:** Approve this plan (no code yet)  
2. **Next:** Reply `Execute B0-a through B0-d` (or execute one slice)  
3. Composer implements on `cursor/batch0-brain-presentation-impl-e7f9`  

---

## Suggested human replies

```text
Plan approved — do not execute yet
```

```text
Execute B0-a through B0-d
```

```text
Execute B0-a only
```
