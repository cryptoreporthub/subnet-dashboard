# Ditto takeover handoff — all agents + Opus transition

**Created:** 2026-08-03  
**main:** `3e13e0a` (#787 hydrate plan closed)  
**Purpose:** Single artifact for Ditto to resume orchestration after Opus chat ended.  
**Protocol:** `ditto-cursor-handoff.md` — git lock is spec; Ditto is index + STATUS.

---

## STATUS SNAPSHOT

| Item | State |
|------|--------|
| Prod | Fly v1 inline worker stable; `/health` OK |
| Hydrate desk P1–P3 | **CLOSED** (#781–#787) — daily-pick honest HOLD, trust banner honest, judges no naked busy |
| Frontend mist/pewter wave | **MERGED** (#767–#779) — thumb dock, ui.css shell, dead CSS purge |
| Post-hero finish queue Steps 0–6 | **DONE** on main through #765 era |
| **Opus tribunal hero** | **OPEN DRAFT** PR #788 — preview only, **not live-wired** |
| Human gates | 390px hero glance (post-layout); H2 soak **2026-08-04**; H3 **2026-08-11** |
| Accuracy lift / Slice 7 | **GATED** until H2 GO |

---

## OPUS CHAT — TAKEOVER BRIEF (priority)

### Agent identity

| Field | Value |
|-------|--------|
| Run name | Product A+ enhancement |
| bcId | `bc-019fc55e-26c7-7815-aa3c-5f689223192d` |
| Model | `claude-opus-5-thinking-low` |
| Branch | `cursor/tribunal-hero-redesign-192d` |
| PR | **#788** (draft, open) |
| Run status | ERROR (pod gone after deliverables; setup succeeded; not user-killed) |
| URL | https://cursor.com/agents/bc-019fc55e-26c7-7815-aa3c-5f689223192d |

### What Opus was asked to do

Redesign the council hero as a **tribunal** metaphor: sealed case, four expert benches (Quant / Hype / Dark Horse / Technical), conviction spectrum, docket strip — on locked mist/pewter tokens from the Grok frontend wave (#767–#779).

**Explicit constraint:** preview/sign-off first. Do **not** replace live `#k3-layer-claim` in `council_stage.html` until human approves visuals.

### What Opus shipped (PR #788, commit `6fcbdb9`)

| File | Role |
|------|------|
| `internal/learning/dpick_tribunal.py` | Derives `tribunal` block from existing `expert_contributions` — no new scoring |
| `internal/preview/tribunal.py` | SSR preview route handler |
| `templates/partials/premium/tribunal.html` | Tribunal partial (preserves `#k3-action-badge`, `#k3-orb-score`, `#k3-call-headline` for future JS wire) |
| `templates/preview/tribunal.html` | Preview shell |
| `static/css/ui.css` | +499 lines tribunal CSS on mist/pewter tokens |
| `server.py` | `/preview/tribunal` + tribunal attach on daily-pick path |
| `tests/test_dpick_tribunal.py` | Unit tests (92 lines) |
| `tests/test_endpoint_contract.py` | Contract route added |

**API behavior (derived, fail-soft):**
- Maps expert scores → stances: BUY ≥0.58, SELL ≤0.42, else HOLD
- UI states: `sealed | gated | forming | cold`
- Gated HOLD uses `candidate` when `pick` is null
- `attach_tribunal_to_daily_pick` never raises

**Preview URLs (after merge):**
- `/preview/tribunal?state=sealed` — sealed BUY
- `/preview/tribunal?state=gated` — honest gate HOLD
- `/preview/tribunal?state=forming` — empty benches
- `/preview/tribunal?state=cold` — cold empty

**Tests claimed green:** `pytest tests/test_dpick_tribunal.py tests/test_endpoint_contract.py` — 148 passed.

### What Opus did NOT do (intentionally deferred)

- Wire tribunal into live `templates/partials/premium/council_stage.html`
- Replace `#k3-layer-claim` on homepage
- Human 390px visual sign-off
- Mark PR ready for review (still draft)

### Human decisions required (before Ditto/Cursor continues)

1. **Visual GO / NO-GO** on tribunal concept v3 — review PR #788 screenshots + live preview after deploy
2. **If GO:** approve follow-up slice to wire `tribunal.html` into `council_stage.html` + hydrate path
3. **If NO-GO:** iterate on preview branch or abandon; do not blind-merge

### Recommended next slice for Ditto (after human GO)

```
LOCK_PATH: cursor-agents-communication/tribunal-live-wire-lock.md  (create on GO)
BRANCH: cursor/tribunal-live-wire-192d (continue from #788)
TYPE: DESIGN-HEAVY
MODELS: Grok medium LOCK → Sonnet on LOCK → Composer 2.5 implement → Grok post-build
AC:
- [ ] Live hero uses tribunal partial when tribunal block present on /api/daily-pick
- [ ] Hydrate path updates orb/badge/headline via preserved IDs
- [ ] 390px sealed + gated readable
- [ ] g0_phone_qa.sh PASS
- [ ] No fake conviction when data missing
NON-GOALS: rescoring, new expert weights, pd/pds card extract
```

### Do not confuse with stale drafts

| PR | Why ignore |
|----|------------|
| #692, #675, #374 | Superseded by ground-up mandate; ideas only |
| #686 | SN6 name — separate tiny fix if still wanted |
| #650 | Superseded by main ledger heal |

---

## ALL AGENTS — WORK SUMMARY

### 1. Live website interface (Grok) — DONE

| Field | Value |
|-------|--------|
| bcId | `bc-019fc1e5-5dfb-78b2-85f8-121e1dc9458c` |
| Branch | `cursor/frontend-mist-drift-458c` |
| Status | IDLE — work complete |

**Merged PRs:** #767–#779 (full mist/pewter UI), then #781–#787 (hydrate P1–P3).

**Deliverables:** mist drift atmosphere, thumb dock, skel/aurora, kinetic wordmark, OG share, tour restyle, CSS purge, Fly QA hotfix, audit hardening. Serial hydrate fixes closed in `hydrate-desk-investigation-plan.md`.

**Open:** possible console-error triage (artifact `console_errors.webp`); no blocking PR.

---

### 2. Visual audit / board coordination (Grok) — MOSTLY DONE

| Field | Value |
|-------|--------|
| bcId | `bc-019f895a-02ef-77ec-bd0b-25ae75d81d2f` |
| Branch | `cursor/board-g0-status-1d2f` |
| Status | IDLE |

**Scope:** Long-running coordination — board status, hero sprint, mindmap GIL unwedge (#752–#765), learning-health cache, API timeout chain.

**Open PRs:** #404 (board status doc), #532 (Ditto↔Cursor handoff protocol draft).

---

### 3. API timeout wrappers + Phase C (Composer) — DONE

| Field | Value |
|-------|--------|
| bcId | `bc-019fc0df-e046-7833-b6f2-b93fb13774b2` |
| Branch | `cursor/phase-c-mindmap-wiring-1d2f` |
| Status | IDLE |

**Merged:** #734, #737, #741, #751, #753, #754, #766 — timeout wrappers, Phase C mindmap display wiring, mindmap endpoint bounds.

---

### 4. Smoke readability + API unwedge (Grok) — DONE

| Field | Value |
|-------|--------|
| bcId | `bc-019fbe3c-3bd8-7a32-88ca-d21e331b7e40` |
| Branch | `cursor/judges-simivision-stale-first-7e40` |
| Status | IDLE |

**Merged:** #726, #730, #743, #756, #759, #761, #765 — smoke scrim, stale-first judges/simivision, soul_map deepcopy fix.

---

### 5. Three-state confidence + finish queue (Grok) — DONE

| Field | Value |
|-------|--------|
| bcId | `bc-019fbe30-5f55-7adb-9570-77a6433aece3` |
| Branch | `cursor/mindmap-graph-skip-full-state-ece3` |
| Status | IDLE |

**Merged:** #724–#735, #739–#750 — three-state confidence, mindmap integration honesty (M1–M5), hero A-tier, graph skip full state, premium dedupe, bridge honesty, LB-11 trail fix, 390px sign-off pack, board sync.

---

### 6. Agent L (learning loop) — DONE (Aug 1 era)

**Handoff:** `handoff-agent-l-learning-loop-2026-08-01.md`  
**Merged:** #719–#721 (soul_map cache, judges weights, MI author trust), Phase C display (#741).

---

### 7. Agent H (hero + mindmap design) — DONE (Aug 1 era)

**Handoff:** `handoff-agent-h-hero-mindmap-2026-08-01.md`  
**Merged:** #729, #731, #732, #736 — mindmap loop integration, visual spine, hero ACs.

**Note:** Opus tribunal (#788) is a **new** hero direction on top of Agent H work — needs explicit human approval before replacing live hero.

---

## ACTIVE GATES (obey before new build slices)

| Gate | When | Action |
|------|------|--------|
| Tribunal visual GO | **Now** | Human reviews PR #788 preview; Ditto records GO/NO-GO |
| Human 390px glance | After layout | `hero-mindmap-390-signoff-2026-08-02.md` — still PENDING |
| H2 Track 1 soak | **2026-08-04** | `soak_review_snapshot.sh` → GO/NO-GO |
| H3 soak | 2026-08-11 | same |
| Accuracy lift Slice 7 | After H2 GO only | `accuracy-pump-pattern-plan.md` |

---

## PROD STATE (post-#787)

- Daily pick: honest HOLD (confidence gate / scheduler — not eternal "forming")
- Trust banner: honest `1/30` with shadow_graded explanation (#785)
- Judges: volume last-good cache; no naked `busy` (#786)
- Frontend: mist/pewter stack live (#767–#779)
- Mindmap: non-5xx; 0.5–17s depending on cache warmth
- Babysit sprint + g0: green as of 2026-08-02 (re-run after tribunal merge)

---

## DITTO NEXT ACTIONS

1. **Read this file** + `board.md` + `hydrate-desk-investigation-plan.md` (CLOSED)
2. **Post STATUS** memory: `main=3e13e0a`, Opus PR #788 awaiting human visual GO
3. **On human GO for tribunal:** create `tribunal-live-wire-lock.md`, assign Composer slice, continue branch `cursor/tribunal-hero-redesign-192d`
4. **On human NO-GO:** close or iterate #788; do not wire live hero
5. **Aug 4:** run H2 soak checkpoint; block accuracy experiments until GO
6. **Do not** blind-merge stale drafts (#692, #675, #686, #650)

---

## KEY FILE INDEX

| Topic | Path |
|-------|------|
| Board | `cursor-agents-communication/board.md` |
| Post-hero queue | `cursor-agents-communication/post-hero-finish-plan.md` |
| Hydrate investigation (closed) | `cursor-agents-communication/hydrate-desk-investigation-plan.md` |
| Two-agent split (Aug 1) | `cursor-agents-communication/two-agent-split-2026-08-01.md` |
| Model rules | `cursor-agents-communication/model-guide.md` |
| Ditto protocol | `cursor-agents-communication/ditto-cursor-handoff.md` |
| Opus PR | https://github.com/cryptoreporthub/subnet-dashboard/pull/788 |
| Opus run | https://cursor.com/agents/bc-019fc55e-26c7-7815-aa3c-5f689223192d |

---

LOCK_PATH: cursor-agents-communication/ditto-opus-transition-handoff-2026-08-03.md  
STATUS: promoted  
WAIT_FOR: human tribunal visual GO on PR #788
