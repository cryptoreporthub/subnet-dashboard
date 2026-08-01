# AGENT H — Hero + Mindmap DESIGN-HEAVY handoff (2026-08-01)

**YOU ARE AGENT H.** Not the learning-loop merge / Phase C agent.  
**Sibling:** Agent L → `handoff-agent-l-learning-loop-2026-08-01.md` · PR #722 · merges #719–#721 · Phase C  
**Full plan:** `hero-mindmap-sprint-plan.md` · PR #723  
**Index:** `two-agent-split-2026-08-01.md`

---

## Your objective (only this)

| Task | Goal |
|------|------|
| **Task 1** | Hero **B → A** — presentation + best-in-class logic (ground-up, not finishing #692) |
| **Task 2** | Mindmap **next level** — DESIGN-HEAVY visual + integration *audit* + §30 gaps Phase C does **not** cover |

**Above-fold hero** = `council_stage.html` (K3 dossier / conviction orb), **not** demoted `hero.html`.

**North star:** Attentive human checking 1–2×/day can act in time (`gameplan-pump-site-undeniable.md` build test).

**Not your job:** Merging #719–#721, Phase C display wiring (dev signals / judge portfolio summary / MI author trend / pump snapshot display), editing `model-guide.md` / `board.md` (Agent L / #722).

---

## Models (DESIGN-HEAVY)

Cite `model-guide.md` § “Exactly ONE Sonnet gate per slice”.

| Role | Model |
|------|--------|
| Audit / LOCK / fix | **Grok** slow + **medium** → escalate **high** if stuck |
| **One Sonnet gate** | On the **LOCK before Composer** (low → medium if stuck). Read-only — never edits |
| Build | **Composer 2.5** after Sonnet PASS |
| Post-build review | **Grok** only — **do not** also Sonnet the Composer diff (double-dip) |

```text
Grok LOCK (medium→high)
  → Sonnet (low→medium) on LOCK once
  → if FAIL: Grok remediates LOCK → Composer patch → Sonnet re-checks SAME gate
  → Composer implement
  → Grok post-build review + babysit
```

---

## Wait for Agent L before overlapping files

**Do not start Composer on mindmap shared files until Agent L Phase C has merged** (or human says Phase C deferred).

Shared risk files: `mindmap_graph.js`, `mindmap_aggregator.py`, `panel_summaries.py`, mindmap routes.

You **may** start Phase 0–2 Grok audit/LOCKs (read-only) anytime.

**Merge order:** #722 → #719 → #720 → #721 → Phase C → **then your Task 1/2 PRs**.

---

## Ground-up mandate

Jul 30–Aug 1 polish and drafts **#692 / #675 / #633 / #374** = **reference only**. Re-audit. Do not blind-merge or “continue where they left off.”

---

## Phase 0 deliverables (before Composer)

1. **Hero LOCK** — single source of truth for daily-pick/hero hydrate; failure modes; 5–7 A-tier AC
2. **Mindmap LOCK** — integration matrix (writer → store → API → UI → closes loop?); gaps vs `living-brain-audit.md`
3. List what prior agents left incomplete
4. Explicit defer of anything owned by Agent L Phase C

---

## Task 2 vs Agent L Phase C

| Agent L Phase C (MECHANICAL) | You Task 2 (DESIGN-HEAVY) |
|------------------------------|---------------------------|
| Wire existing closed-loop *data* into summary/trail | Hero↔mindmap visual spine; narrative weight |
| Dev signals / portfolios / author trend / snapshots | Integration audit; stub conviction honesty; LB-11 dedupe; optional §30 LB-5/6 scoring |
| No weight math | Loop-closure only if Phase C skipped it and LOCK says so |

---

## Key files (your lane)

**Hero:** `templates/partials/premium/council_stage.html`, `static/js/cockpit_hydrate.js`, `home_live_refresh.js`, `trust_banner_ui.js`, `internal/learning/dashboard_context.py`

**Mindmap (after Phase C rebase):** `static/js/mindmap_graph.js`, `living_focus.js`, `internal/mindmap/graph.py`, `internal/learning/mindmap_aggregator.py` — only DESIGN-HEAVY deltas

**Read:** `living-brain-audit.md`, `post-s30-living-brain-plan.md`, `gameplan-pump-site-undeniable.md`

---

## Branches (after Sonnet PASS on LOCK)

- `cursor/hero-a-tier-ground-up-1d2f`
- `cursor/mindmap-loop-integration-1d2f`
- optional: `cursor/mindmap-visual-spine-1d2f`

---

## Definition of done

**Task 1:** 10s @390px — LONG or honest HOLD + why + evidence; one render path; no fake data; tests green  
**Task 2:** integration matrix in PR; no `conviction: 50` stub; graph+trail in contract test; focus-scoped learn strip; visual bar met; Phase C items **not** re-done

---

## Paste-ready prompt — AGENT H

```text
You are AGENT H on cryptoreporthub/subnet-dashboard.

READ FIRST:
1. cursor-agents-communication/two-agent-split-2026-08-01.md
2. cursor-agents-communication/handoff-agent-h-hero-mindmap-2026-08-01.md
3. cursor-agents-communication/hero-mindmap-sprint-plan.md  (PR #723 @ 2016e71+)
4. model-guide.md § Exactly ONE Sonnet gate (via #722 if not on main)
5. living-brain-audit.md · gameplan-pump-site-undeniable.md · AGENTS.md · ponytail

YOU ARE NOT AGENT L. Do not merge #719–#721 or do Phase C display wiring.
Sibling Agent L owns: handoff-agent-l-learning-loop-2026-08-01.md / PR #722.

OBJECTIVE (GROUND UP):
Task 1: Hero B→A (council_stage above-fold, not demoted hero.html)
Task 2: Mindmap DESIGN-HEAVY visual + integration audit + §30 gaps Phase C skips
Reference only: #692 #675 #696 — do not blind-finish.

GATE: Wait for Agent L Phase C (or human defer) before Composer edits to shared mindmap files. You MAY run Phase 0–2 Grok audit/LOCKs now.

MODELS (DESIGN-HEAVY):
- Grok medium→high: audit + LOCK
- Sonnet low→medium: ONE gate on LOCK before Composer (never edits)
- Composer 2.5: implement only after Sonnet PASS
- Post-build: Grok only — do NOT Sonnet the Composer diff
- Sonnet finds → Grok fix LOCK → Composer patch → Sonnet same gate only

START: Phase 0 Grok LOCKs for hero + mindmap; post to PR/Ditto; Sonnet gate; then Composer on hero branch first if Phase C still open.
Babysit: ./scripts/babysit_phase.sh c && check_learning_loop.sh + daily-pick + mindmap APIs.
```
