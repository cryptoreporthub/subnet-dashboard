# Cursor Implementation Guide

This guide is for Cursor (Composer + Grok) to pick up the visual/iterative UI tasks. Ditto Code handles surgical fixes separately.

## Tool Assignment

- **Composer 2.5** — structural multi-file work (splits, partials, htmx)
- **Grok (xhigh)** — visual/UX fixes, audits, architecture decisions
- **Grok-fast-xhigh** — pre-merge behavioral reviews and audits
- Composer auto-invokes Grok via subagent for design/audit tasks per `model-guide.md`

## Phased Plan (Sequential — Most Tasks Cannot Run in Parallel)

### Phase 1: Composer — Structural Splits
**C1: Split `static/css/style.css` into 6 focused files**
- `base.css`, `layout.css`, `dashboard.css`, `premium.css`, `chat.css`, `responsive.css`
- Update all template `<link>` tags accordingly
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

## Ditto Code Scope (Do NOT Touch These)

Ditto Code handles these in a separate PR:
- Delete 35 junk files + 15 diagnostic workflows
- Fix XSS in chat (`innerHTML` → `textContent`)
- Pin `requirements.txt` versions
- Fix `X-Frame-Options` invalid value
- Remove `pandas` if unused
- Fix undervalued score "DEEP VALUE" logic
- Fix `loading.html`, remove `.bak` files
- Remove `--text-muted` if Ditto's fix supersedes G5
- Add favicon (if not done by G12)
- Fix APY/confidence double-multiply (if not done by C5/C6)

Coordinate via board to avoid duplicate work on overlapping items.