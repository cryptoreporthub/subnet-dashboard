# Message Intel skeleton + Council hydrate polish

**Created:** 2026-08-04  
**Branch:** `cursor/message-intel-skeleton-council-bars-1d2f`  
**Cadence:** Grok LOCK → Composer → Sonnet review → merge → Grok babysit → human 390px

## Goal

Dress the degraded homepage shell using the existing `.hydrate-skeleton` system. Council uses **soul-orb constellation** (main as of #813); trend colors prefer real `recent_expert_weight_deltas()` when available.

## Sonnet review (2026-08-04) — PASS after polish

- Skeleton in `#message-intel-feed` + council empty branch (not wbar regression)
- Delta-driven soul-orb trend when trail has weight_change rows; weight-vs-baseline fallback
- `aria-live` / `aria-busy` / `sr-only` / staggered shimmer
- JS `soulTrendFromDelta` + ranked orb order matches SSR

## Files

| File | Change |
|------|--------|
| `templates/partials/premium/message_intel_feed.html` | Skeleton in live feed panel |
| `templates/partials/premium/council.html` | Empty-branch skeleton + `aria-live` |
| `static/css/ui-legacy.css` | `--tall`, `.sr-only`, stagger delays |
| `internal/learning/dashboard_context.py` | Delta-aware `_council_weights_list` |
| `static/js/cockpit_hydrate.js` | `soulTrendFromDelta`, ranked render |
| `static/js/message_intel_feed.js` | Clear `aria-busy` after hydrate |
| `tests/test_fast_shell_context.py` | Skeleton + delta trend unit test |

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev
curl -s $BASE/health
curl -s $BASE/ | grep -E 'hydrate-skeleton|message-intel-feed|soulmap-constellation'
./scripts/check_learning_loop.sh
```
