---
name: Smoke DS consumption rules
description: New visual treatments must live in the Smoke design system, not in consumers; new color tokens need template placeholders or they silently produce no CSS var.
---

**Rule:** Any new visual treatment a consumer needs (new hue, surface style, backdrop) must be added to the Smoke design system first — as a token and/or a product-agnostic component — and then imported. Consumers must not carry raw color/gradient/blur/shadow literals, even in mockups.

**Why:** The Smoke docs make tokens/components the single source of truth for the whole product; inline literals in one consumer drift from the palette and can't be reused by the next surface.

**How to apply:** Adding a color to `tokens.json` alone is not enough for web — the token build only substitutes placeholders that already exist in the theme template, so a new color must also be wired into the template (theme mapping + light/dark blocks) or it silently never becomes a CSS variable while still appearing in the generated tokens object. Derive translucent variants in components with `color-mix(...)` over token vars rather than new rgba literals.
