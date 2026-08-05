# Phase 3 — execution plan (highest leverage first)

**Started:** 2026-08-05  
**Branch:** `cursor/phase3-tribunal-tests-6006`

## Priority queue

| # | Slice | Leverage | Scope |
|---|-------|----------|-------|
| P3-0 | Tribunal test realignment | **Highest** — unblocks CI confidence on council hero | `tests/test_visual_upgrade_polish.py` → tribunal-hero v4 contracts |
| P3-1 | Share/judge fonts | Medium — brand consistency | `templates/share/base_share.html`, `templates/judge_council.html` → Space Grotesk |
| P3-2 | Home SEO / babysit warnings | Medium — prod polish | NFA disclaimer, `og:image` on home **instant shells** |
| P3-3 | `ui-legacy.css` purge | Lower — large diff, incremental | **P3-3a done:** tribunal conf-state → `ui.css`; dead k3-orb conf-state rules removed |

## P3-0 — tribunal test realignment

**Problem:** `test_visual_upgrade_polish.py` still asserts legacy k3-orb markup (`digit-ones`, inline `<style>` conf-state CSS, `k3-claim` identity bands). Live hero is **tribunal-hero v4** inside `#k3-dossier`.

**New contracts (assert instead):**

- `#k3-dossier[data-conf-state]` still drives H1 three-state SSR (resolving / zero / value).
- Gauge display via `#k3-orb-score[data-gauge-value]` + `build_tribunal_view().gauge_display` (`—`, `0%`, `50%`, …).
- Tribunal structure: `#tribunal-hero`, `tribunal-hero__gauge-fill`, judge `data-judge` hooks.
- Motion/CSS lives in `static/css/ui.css` (tribunal keyframes + reduced-motion), not inline in `council_stage.html`.
- Identity band → `data-hero-netuid` on dossier + `k3SyncNetuidBand()` in stage script.
- Horizon badge SSR-hidden; hydrate unhides via `patchK3DossierFromPayload`.
- Soul-map hydrate trend → `soulTrendFromDelta` (delta-first, weight fallback).

**Do not duplicate:** `tests/test_tribunal_hero_live.py`, `tests/test_tribunal_hero_preview.py` — polish tests stay markup/hook guards only.

## Gate

- `tests/test_visual_upgrade_polish.py` — **0 failures**
- Full pytest failures ≤ 72 (no regressions elsewhere)
- Contract guard 144 passed
