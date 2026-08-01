# Hero + Mindmap sprint — ground-up quality pass

**Created:** 2026-08-01 · **Updated:** 2026-08-01 (aligned to `model-guide.md` ONE Sonnet gate)  
**Baseline main:** `73a0736` (#718 soul_map gateway · post-wedge stability)  
**Slice type:** **DESIGN-HEAVY** → Sonnet once on the **LOCK before Composer**; post-build review = **Grok** only (do not also Sonnet the Composer diff by default — that double-dips).  
**Mode:** **Grok** (medium → high if stuck) LOCK + remediates · **Sonnet** (low → medium if stuck) on LOCK only · **Composer 2.5** implements  
**Mandate:** **Do not continue** partial hero/mindmap work as-is. Use Jul 30–Aug 1 commits and open PRs (#692, #675) as **reference only**. Ship Task 1 and Task 2 **from a fresh spec** after audit.  

**Hard gate:** Composer must **not** implement until Sonnet low (or medium) reviews the LOCK and returns PASS / CONDITIONAL. If Sonnet finds problems → **Grok fixes** (re-LOCK) → Sonnet re-reviews **that same gate** → only then Composer. Canonical rule: `model-guide.md` § “Exactly ONE Sonnet gate per slice” (lands via sibling PR **#722** if not yet on `main`).

---

## Agent ownership — do not conflict

**Sibling handoff (other agent):** `handoff-learning-loop-mindmap-2026-08-01.md` · PR **#722**

| Owner | Owns | Do not touch |
|-------|------|--------------|
| **#722 / learning-loop agent** | Merge **#719 → #720 → #721**; **Phase C** mindmap *display* wiring (dev signals, judge portfolios/postmortems, MI author reliability trend, pump desk snapshots); `model-guide.md` ONE Sonnet gate; board STATUS for that track | Hero B→A redesign; DESIGN-HEAVY mindmap visual spine |
| **This plan / hero-mindmap agent** | **Task 1** hero B→A (ground-up); **Task 2** DESIGN-HEAVY mindmap narrative + integration *audit* + §30 loop gaps **not** covered by Phase C | Do **not** re-do Phase C wiring; do **not** merge #719–#721; do **not** edit `board.md` / `model-guide.md` in this PR (cite #722) |
| **Draft polish PRs** | #692, #675, #633, #374 | **Reference only** — cherry-pick ideas into LOCK; do not blind-merge or rebase-steal |

**Task 2 vs Phase C (critical):**

- Phase C (#722) = **MECHANICAL** display wiring of already-closed loops into mindmap summary/trail.
- This sprint Task 2 = **DESIGN-HEAVY** hero↔mindmap visual + verify integration matrix + optional §30 loop-closure slices Phase C explicitly skips (e.g. LB-5/6 scoring, LB-11 dedupe, stub conviction honesty).
- If both would edit the same file (`mindmap_graph.js`, `mindmap_aggregator.py`, `panel_summaries.py`): **#722 Phase C merges first**; this agent rebases and only changes what Phase C did not cover.

**Merge order recommendation:**

```text
#722 (docs + model-guide) → #719 → #720 → #721 → Phase C PR(s)
THEN hero-mindmap Task 1 / Task 2 PRs (this plan)
```

**This PR (#723) ships docs only:** `hero-mindmap-sprint-plan.md`. No `board.md` / `model-guide.md` edits (avoids conflict with #722).

---

## User tasks (canonical)

| Task | Goal |
|------|------|
| **Task 1** | Hero **B → A** — presentation first, but logic and code must be best-in-class |
| **Task 2** | Mindmap **next level** — brainstorm + verify **everything** integrated with mindmap + learning loop; visual weight matches importance |

**North star (internal):** Attentive human checking 1–2×/day can act in time — hero = conviction now, mindmap = proof the brain is learning (`gameplan-pump-site-undeniable.md` build test).

**Above-fold hero** = `council_stage.html` (K3 dossier / conviction orb), not demoted `hero.html` market KPI block.

---

## Model workflow (mandatory)

**Cite `model-guide.md` — do not invent a competing pipeline.**  
This sprint is **DESIGN-HEAVY**, so the single Sonnet gate is on the LOCK (before Composer). Post-build = Grok. Do **not** also run a full Sonnet pass on the Composer diff unless Grok escalates residual risk (rare spot-check).

| Role | Model | Thinking |
|------|--------|----------|
| Quarterback / auditor / LOCK / fixer | **Cursor Grok** | **slow + medium** default; escalate **high** only if medium FAIL / stuck; **never xhigh** unless human says so |
| **One Sonnet gate (this sprint: on LOCK)** | **Sonnet** | **low** default; **medium** only if low cannot decide / deep issues. Read-only — never edits |
| Implementation | **Composer 2.5** | Builds Sonnet-approved LOCK; `composer-2.5-fast` only for mechanical follow-ups |

```text
Phase 0 — Grok slow+MEDIUM (audit quarterback)
  Audit prod + repo · find root gaps · short LOCK per task
  Escalate to slow+HIGH only if medium FAIL / stuck / unsatisfactory
  NO implementation yet

Phase 1 — Grok slow+MEDIUM (hard diagnosis; HIGH if stuck)
  Hero data-path + mindmap integration matrix · decide what to fix first
  Output: short LOCK (VERDICT, DECISIONS, FILES, AC, RISKS) — model-guide template
  Cap ~1 screen each LOCK — Grok must NOT author long prose plans

Phase 2 — Grok slow+MEDIUM (visual LOCK only, after out of weeds; HIGH if stuck)
  Hero A-tier presentation + mindmap narrative spine
  Structured LOCK only — no long design essays

Phase 2.5 — Sonnet LOW on LOCK (THIS SPRINT'S ONLY SONNET GATE)  ← required
  Review Phase 0–2 LOCKs + proposed file list + AC
  Escalate to Sonnet MEDIUM only if LOW cannot resolve or finds deep risk
  Return: PASS | CONDITIONAL | FAIL with bullet findings
  If FAIL / CONDITIONAL with must-fix items:
    → Grok remediates at medium (HIGH if still stuck)
    → Sonnet re-reviews THAT SAME gate (low, then medium if still stuck)
    → Loop until PASS (or human override)
  Composer is BLOCKED until Sonnet PASS (or CONDITIONAL with only deferred non-blockers)
  Do NOT schedule a second full Sonnet review of the Composer diff by default

Phase 3 — Composer 2.5 (implementation)
  Expand Sonnet-approved LOCK into PR body · implement · ponytail · one PR per task
  Composer must NOT invent design details missing from the LOCK
  Orchestrator smoke-checks diff scope + new tests

Phase 4 — Grok slow+MEDIUM (post-implement review; HIGH if behavioral risk)
  Diff review · 390px QA checklist · integration re-verify · babysit · merge recommendation
  Optional rare: Sonnet low spot-check ONLY if Grok flags residual risk (not a second default gate)
```

**Do not** let Composer invent design or start coding before Sonnet gate.  
**Do not** let Sonnet implement the fixes — Sonnet finds; **Grok fixes**; Composer builds.  
**Do not** Sonnet both LOCK and post-Composer diff (double-dip).  
**Do not** skip Phase 0 audit because #692 or #696 exist.  
**Do not** default Grok to xhigh / fast-xhigh.  
If Sonnet quota is exhausted mid-sprint: stop at Phase 2.5, post LOCKs for human, do **not** skip the gate silently.

---

## Reference only (not “done”)

| Artifact | Treat as |
|----------|----------|
| `09a1add` 6-color hero / conviction board | Starting visual language — re-validate |
| `fbb8c7e` / #696 subnet-grouped Trail | Trail UI v1 — may replace if LOCK says better |
| `729e5a4` whale/rugger/indicator graph nodes | Verify still correct after ground-up pass |
| Draft PR **#692** hero + conviction polish | Cherry-pick ideas; **do not merge blind** |
| Draft PR **#675** hero netuid-band accents | Optional input to LOCK |
| `post-s30-living-brain-plan.md` §30-1…10 | Backlog for Task 2 integration — prioritize in LOCK |
| `living-brain-audit.md` | Source of truth for loop gaps |

---

## Phase 0 — Audit deliverables (before any UI code)

### Task 1 audit — Hero

Answer in LOCK:

1. **Source of truth** — What is the single canonical payload for above-fold hero? (`/api/daily-pick`, SSR `dashboard_context`, hydrate order, worker proxy path)
2. **Failure modes** — Stuck loading, SSR downgrade, stale `data-generated-at`, HOLD vs LONG honesty, orb empty states
3. **Presentation gaps** — vs gameplan build test (morning + afternoon decision in 10s @390px)
4. **Code quality** — Duplicated render paths in `cockpit_hydrate.js` / `home_live_refresh.js` / `trust_banner_ui.js`; tighten to one path
5. **A-tier bar** — Define 5–7 measurable AC (not “prettier orb”)

**Files to read:**

- `templates/partials/premium/council_stage.html`
- `static/js/cockpit_hydrate.js` (daily pick / hero render)
- `static/js/home_live_refresh.js`, `static/js/trust_banner_ui.js`
- `internal/learning/dashboard_context.py`
- `internal/learning/routes.py` (`/api/daily-pick`)
- `gameplan-pump-site-undeniable.md` (build test)

### Task 2 audit — Mindmap + learning loop

Produce **integration matrix** (writer → store → API → UI → feeds next pick?):

| Writer | Store / event | API | UI consumer | Closes loop? |
|--------|---------------|-----|-------------|--------------|
| `prediction_loop` | predictions + trail | graph/trail | mindmap, living focus | ? |
| `trail_bus` / resolver | learning_trail | graph/trail | trail.html, hydrate | ? |
| `nudge_expert` | soul_map weights | learning stats | hero weights viz | ? |
| dispositions / scenario / MI / pump | various | graph/state | cockpit | ? |
| whales / ruggers / indicators | stores | graph | mindmap_graph.js | ? |

**Known gaps to verify (not assume fixed):**

- `/api/mindmap/summary` stub `conviction: 50.0`
- Duplicate `/api/mindmap/trail` fetch (LB-11)
- `/api/mindmap/graph` not in contract test
- Dispositions + scenario outcomes **display but don't score** (audit §30)
- `MindmapBridge.get_brain_recommendations()` heuristic fallback
- SSR `data-initial-graph` unwired

**Files to read:**

- `internal/learning/mindmap_aggregator.py`, `trail_bus.py`, `panel_summaries.py`
- `internal/mindmap/graph.py`, `internal/mindmap/routes.py`
- `static/js/mindmap_graph.js`, `living_focus.js`, `cockpit_hydrate.js`
- `living-brain-audit.md`, `post-s30-living-brain-plan.md`

---

## Phase 1–3 — Implementation slices (after LOCK approved)

### Task 1 — Hero A-tier (one PR)

**Scope (adjust per LOCK):**

- One canonical hydrate path; monotonic updates; honest empty/HOLD states
- Visual hierarchy: verb → subnet → % → evidence strip (K3 council hero stack)
- 390px: no wrap breakage; touch targets ≥44px; reduced-motion safe
- Remove or repurpose dead `pds-hero__visual` slot only if LOCK specifies
- Tests: contract or JS smoke for daily-pick hero fields; no fake conviction

**Branch:** `cursor/hero-a-tier-ground-up-1d2f`  
**Babysit:** `scripts/g0_phone_qa.sh` + manual 390px screenshot notes in PR

### Task 2 — Mindmap + loop (one or two PRs)

**2a — Integration truth (ship first):**

- Fix stub/fake data; dedupe trail fetch; contract-test graph + trail
- Emit missing trail events (signal weight nudges if still silent per audit)
- Document matrix in PR body; pytest for critical paths

**Branch:** `cursor/mindmap-loop-integration-1d2f`

**2b — Visual + narrative (after Grok LOCK):**

- Hero netuid ↔ mindmap trail spine (focus SN events surface first)
- Conviction / learning delta visible without opening Market drawer
- Optional: merge 2a+2b if small

**Branch:** `cursor/mindmap-visual-spine-1d2f`

---

## Acceptance (definition of done)

### Task 1 — Hero A

- [ ] Stranger @390px answers in 10s: LONG or honest HOLD + why + one evidence path
- [ ] No eternal spinner; `data-generated-at` / stale badge honest
- [ ] Single render path (document in PR)
- [ ] `pytest` + contract green; Fly deploy babysit green
- [ ] Human 390px sign-off recorded in PR or Ditto

### Task 2 — Mindmap + loop

- [ ] Integration matrix in PR — every major writer classified (display vs closes loop)
- [ ] No fake conviction in mindmap APIs
- [ ] `/api/mindmap/graph` + `/api/mindmap/trail` in contract test
- [ ] Living Focus learn strip shows only focus-netuid events (LB-3)
- [ ] At least one §30 integration slice shipped OR explicit defer with ticket (LB-5/6/7 priority in LOCK)
- [ ] Visual: mindmap feels as important as hero (Grok LOCK criteria met)
- [ ] `pytest tests/test_phase_g_mindmap*.py` + new integration tests green

---

## Out of scope (this sprint) — also avoids agent collisions

- split_v2 re-enable (v1 inline worker is canon post-#706)
- Phase 4 accuracy lift / soak sign-off (human Aug 4)
- Merging or rebasing **#719 / #720 / #721** (other agent)
- Phase C display wiring listed in `handoff-learning-loop-mindmap-2026-08-01.md`
- Chutes billing / live LLM chat
- Sitewide cyberpunk re-theme (only hero/mindmap coherence)
- Merging #692 without re-audit
- Editing `board.md` or forking `model-guide.md` in hero-mindmap PRs

---

## Conflict surface

| File | Rule |
|------|------|
| `server.py` + `tests/test_endpoint_contract.py` | Add routes with tests; rebase after #719–#721 / Phase C |
| `data/soul_map.json` | Use gateway (#718); never commit local churn |
| CSS: `council_first.css`, `layout.css`, `responsive.css` | Coordinate hero + mindmap; don't fight Telegram flagship CSS |
| `board.md` / `model-guide.md` | **Owned by #722 this cycle** — cite, do not fork |
| Mindmap summary/trail display wiring | **Phase C (#722)** first; this agent only DESIGN-HEAVY deltas after rebase |

---

## Babysit (every merge)

```bash
BASE=https://subnet-dashboard.fly.dev
./scripts/babysit_phase.sh c
./scripts/check_learning_loop.sh
curl -fsS $BASE/api/daily-pick | jq '{action,netuid,confidence}'
curl -fsS $BASE/api/mindmap/trail | jq 'length'
curl -fsS $BASE/api/mindmap/graph | jq '{status,nodes:(.nodes|length)}'
```

---

## Ditto

After Phase 0 LOCK and after each merge: `save_memory` STATUS with `main=<sha>`, task, PR link.
