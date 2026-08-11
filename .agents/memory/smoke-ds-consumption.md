---
name: Smoke DS consumption rules
description: New visual treatments must live in the Smoke design system, not in consumers; new color tokens need template placeholders or they silently produce no CSS var.
---

**Rule:** Any new visual treatment a consumer needs (new hue, surface style, backdrop) must be added to the Smoke design system first — as a token and/or a product-agnostic component — and then imported. Consumers must not carry raw color/gradient/blur/shadow literals, even in mockups.

**Why:** The Smoke docs make tokens/components the single source of truth for the whole product; inline literals in one consumer drift from the palette and can't be reused by the next surface.

## Static (non-bundler) consumers: serve a generated theme, don't copy values
Non-bundler consumers (e.g. plain static CSS apps) can't import the DS stylesheet directly (it pulls in Tailwind), but review rejects both hardcoded palette values AND hand-mirrored token bridges.
**Why:** the DS docs require tokens as the source of truth "without copying token values".
**How to apply:** serve a theme-only CSS *generated from the DS source* ahead of the app's CSS, and reference the DS variables. Regenerate from source; never hand-edit the generated file.

## Cosmic-glass mobile blur gate must be global, not per-selector lists
Maintaining parallel selector lists for mobile-reset/desktop-enable/reduced-transparency always misses panels (pseudo-elements, rules nested inside mobile media queries) and gets rejected.
**Why:** mobile-first zero GPU cost is a hard review constraint; any ungated `backdrop-filter` fails the pass.
**How to apply:** one global `* , *::before, *::after { backdrop-filter: none !important }` base reset, then re-enable blur only inside the desktop/fine-pointer gate nested in `@media not (prefers-reduced-transparency: reduce)`. Audit with a script that maps every `backdrop-filter` line to its selector.

## Fixed full-page substrate stacking
A fixed background element at `z-index:0` hides EVERY unpositioned body child, including loose elements after the content block (e.g. a disclaimer). Promote all direct body content with `position:relative; z-index:1`, and remember standalone templates don't inherit the main layout — each needs the substrate and token stylesheet wired in (skip templates no route renders).

**How to apply:** Adding a color to `tokens.json` alone is not enough for web — the token build only substitutes placeholders that already exist in the theme template, so a new color must also be wired into the template (theme mapping + light/dark blocks) or it silently never becomes a CSS variable while still appearing in the generated tokens object. Derive translucent variants in components with `color-mix(...)` over token vars rather than new rgba literals.
