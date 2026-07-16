# §23 Share PNG — social crawler compatibility

**Status:** in progress  
**Updated:** 2026-07-16

## Goal

Twitter/LinkedIn/Discord crawlers prefer raster `og:image`; add PNG alongside SVG share cards.

## Slices

| Slice | State | Content |
|-------|-------|---------|
| **S23-1** | 🔄 | `build_og_png()` + `GET .../og.png` (Pillow + DejaVu fonts in Docker) |
| **S23-2** | 🔄 | Share page `og:image` → PNG; modal Save PNG + Copy link |

## RF gates (unchanged)

Trust UI binds `trust_banner` only — share cards show per-call graded stats, not global accuracy.

## Deferred

F7 DNS · A1b Telegram · S5 Discord/X
