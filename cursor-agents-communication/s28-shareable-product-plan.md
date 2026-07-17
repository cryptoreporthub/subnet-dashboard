# §28 — Shareable product (Tier 2)

**Status:** DEFERRED — start after §27-1 + §27-3 ship  
**Updated:** 2026-07-17  
**Baseline:** post-§27  
**Human gate:** Product must feel “finished” (trust shell + brain visible) before spread mechanics.

---

## Goal

Make SimiVision **linkable** — Discord/Telegram deep links, not only in-page scanner clicks.

---

## Queue (sequential · after §27)

| # | Slice | Goal |
|---|-------|------|
| **§28-1** | Subnet pages | `GET /subnet/{netuid}` — SSR or static shell + `/api/report/{netuid}` + pick/judge snippets; link from scanner + hero |
| **§28-2** | Wallet explorer | `GET /wallet/{ss58}` — identity, flows, subnet exposure, rug flags; link from investigation |
| **§28-3** | Global search | Header command palette: subnet name/ID, coldkey, pick id → deep link |
| **§28-4** | Money-flow graph | Wallet↔subnet visualization (optional; largest scope) |

**Existing partial work:** §18 B1 + §20 T4 shipped report panel UX (`subnet_report.js`) — §28-1 promotes to routable pages.

---

## Deferred with §28

- Real-time sell alerts push
- Owner overlay on all reports
- Extrinsic deep links to TaoStats/explorer

## Contract

Same as §27 — branch `cursor/<slug>-c3fd`, contract test updates per new route, no `data/*.json` commits.
