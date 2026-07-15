# Cursor Implementation Guide

This guide is for Cursor (Composer + Grok) to pick up the visual/iterative UI tasks. Ditto Code handles surgical fixes separately.

## Tool Assignment

- **Composer 2.5** — default build; prefer **`composer-2.5-fast`** pool for mechanical slices
- **Grok slow + low/medium** — short design LOCKs / audits only (see `model-guide.md`)
- Composer expands Grok LOCKs into plan markdown, then builds (`grok-lock-composer-write-rule.md`)
- Obey `.cursorignore` + `token-budget-rules.md` for billing-cycle token budget

## Grok Token-Saving Precautions

Grok burns tokens on context + long output. Follow these rules:

1. **Slow + low/medium** — never default to high/xhigh. Escalate high only after medium FAIL/unsatisfactory.
2. **Short LOCK only** — Grok returns VERDICT/DECISIONS/FILES/AC (~1 screen); Composer writes the plan file.
3. **Cache the stable prefix** — unchanged spec first, slice question last.
4. **Batch** — one Grok pass per related group, not one-liner spam.
5. **Scope context** — owned paths only; `.cursorignore` excludes `data/` and superseded designs.
6. **Avoid re-runs** — clear AC first; no “try again” without new evidence.
7. **Skip Grok for trivial changes** — Composer directly for one-line CSS/text/contract adds.
8. **Read binding docs once** — `STATUS.md`, `board.md`, one plan path; cite instead of re-paste.

> **Note:** Prefer **Composer 2.5-fast** for routine implementation. Do **not** use Plan mode every slice when an approved auto-plan exists.

## Phased Plan (Sequential — Most Tasks Cannot Run in Parallel)

### Phase 1: Composer — Structural Splits
**C1: Split `static/css/style.css` into 6 focused files**
- `base.css`, `layout.css`, `dashboard.css`, `premium.css`, `chat.css`, `responsive.css`
- Update all template tags accordingly
- Nothing else may touch `style.css` during this phase

**C2: Split `premium_cockpit.html` into 16 partials**
- Extract each section into `templates/partials/premium/*.html`
- Update include references in the parent template
- Nothing else may touch `premium_cockpit.html` during this phase

### Phase 2: Grok — Quick Visual Fixes (on now-split files)
**G1:** Add canvas wrapper divs in premium cockpit partials for chart responsiveness
**G2:** Fix z-index/overflow on mobile tooltips in the now-split CSS files
**G5:** Fix `--text-muted` contrast color (WCAG AA minimum)
**G6:** Fix magenta stake badge → amber
**G8:** Remove fabricated sparkline data, replace with real or empty state

### Phase 3: Grok — UX + Backend (Parallel-safe, no file overlap)
**G3:** Subnet grouping/collapse affordances (caret UX)
**G4:** Inline style cleanup → move to CSS classes
**G9:** Confidence calibration in `internal/council/state_vector.py`
**G10:** Expert weights in `internal/council/weights.py`
**G11:** Round-robin in `internal/council/resolver_scheduler.py`

### Phase 4: Composer — Hydration Scripts (Sequential, one at a time)
All touch `cockpit_hydrate.js` — must run one after another:
**C4:** Add hydration scripts to `base.html`
**C5:** Fix APY/confidence double-multiply in hydration logic
**C6:** Align conviction tier thresholds between Jinja and JS

### Phase 5: Grok — Final Cleanup
**G7:** Orbitron → Rajdhani swap for section titles (visual judgment)
**G12:** Last cleanup pass — remove `.bak` files, consolidate fonts, add favicon

### Phase 6: Composer — Big One
**C3:** htmx integration (iterative, needs live testing, do last)

## Conflict Matrix

| File | Composer tasks | Grok tasks |
|------|---------------|------------|
| `static/css/style.css` | C1, C5 | G2, G5, G6 |
| `premium_cockpit.html` | C2 | G1, G3, G4 |
| `cockpit_hydrate.js` | C4, C5, C6 | G7 |

This is why phases are sequential — not parallel tracks.

## Rules

1. Read `cursor-agents-communication/board.md` for live status before starting any phase
2. Update the board with your current task before beginning
3. Mark tasks complete on the board when done
4. Do NOT run tasks from a later phase while an earlier phase is in-progress on shared files
5. Only G9, G10, G11 (backend Python) are safe to run in parallel with anything
6. Human review required after each phase before proceeding
7. Commit after each individual task, not just at phase boundaries
8. Run `pytest` and `python -m pytest tests/test_smoke.py` before marking any phase complete
9. Follow all Grok token-saving precautions (see section above)

## Ditto Code Scope (Do NOT Touch These)

Ditto Code handles these in a separate PR:
- Delete 35 junk files + 15 diagnostic workflows
- Fix XSS in chat (`innerHTML` → `textContent`)
- Pin `requirements.txt` versions
- Remove `pandas` if unused
- Fix undervalued score "DEEP VALUE" logic
- Fix `loading.html`, remove `.bak` files
- Remove `--text-muted` if Ditto's fix supersedes G5
- Add favicon (if not done by G12)
- Fix APY/confidence double-multiply (if not done by C5/C6)

> **Updated 2026-07-13 (Phase A handoff — see `docs/IMPLEMENTATION_PLAN.md`):**
> Audit **#11 (`X-Frame-Options` + CORS)** is now **Cursor-owned (A3)**, NOT Ditto.
> Reason: Ditto's GitHub file tools cannot rewrite `server.py` (it exceeds the read limit), so
> the `add_cors_headers` middleware fix must be done by Cursor. Implement it per
> `docs/CURSOR_PROMPTS.md` A3. Do not wait on Ditto for this item.

Coordinate via board to avoid duplicate work on overlapping items.
