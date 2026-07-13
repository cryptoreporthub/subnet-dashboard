# Phase 3 — Grok design + Phase 2 sign-off

**Model:** `grok-4.5-xhigh` (read-only) via Composer subagent  
**Date:** 2026-07-13  
**Scope:** G3 subnet rollup caret UX · G4 inline-style cleanup

## Grok workflow (do not skip)

Per `docs/cursor-implementation-guide.md` + `model-guide.md`:

| Step | Model | When |
|------|-------|------|
| Design / audit | **Grok xhigh** (`grok-4.5-xhigh`) | Before Composer builds Phase 3+ visual/UX |
| Implementation | **Composer** | After Grok spec locked |
| Pre-merge sign-off | **Grok xhigh** | Before merge on behavioral/visual phases |

Token savings: batch related tasks (G3+G4), scope files only, skip Grok for one-liners.

## A) Phase 2 sign-off — CONDITIONAL

| Task | Verdict |
|------|---------|
| G1 structure | PASS |
| G1 paint (Chart.js init) | CONDITIONAL — deferred to Phase 4 C4 |
| G2 mobile overflow | PASS |
| G5 contrast | CONDITIONAL — muted lighter than secondary; fix `#7c8a9e` |
| G6 amber stake | PASS |
| G8 data honesty | PASS |
| G8 UI paint | CONDITIONAL — real closes need C4 binder |

## B) G3 spec

- Add `<span class="subnet-group-caret" aria-hidden="true">` in `subnet_grouping.js`
- CSS caret + `:focus-visible` + 44px touch target + mobile item stack
- Keep localStorage persistence unchanged

## C) G4 spec

Extract static inline styles to classes: `.ti-heat-row`, `.tags-tight`, `.scanner-toolbar`, `.kpi-grid--6`, `.kpi-v-sm`, `.pick-rank--hero`, `.mt-2`/`.mt-3`. Keep dynamic `width:%` and `--ring-pct` inline.
