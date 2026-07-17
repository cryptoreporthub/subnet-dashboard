# §28 — Automated build plan (shareable product)

**Status:** COMPLETE (PR pending)  
**Updated:** 2026-07-17  
**Branch:** `cursor/s28-shareable-c3fd` (stacks §27 + §28)

## Queue

| # | Slice | State |
|---|-------|-------|
| **§28-1** | Subnet pages `GET /subnet/{netuid}` | ✅ in branch |
| **§28-2** | Wallet explorer `GET /wallet/{ss58}` | ✅ in branch |
| **§28-3** | Global search / command palette | ✅ in branch |
| **§28-4** | Money-flow graph (wallet page bars) | ✅ thin in branch |

## AC summary

- Routable subnet + wallet pages with OG meta
- Scanner + hero link to `/subnet/{id}`
- Investigation wallet cells link to `/wallet/{ss58}`
- Header Search + Ctrl/Cmd+K → `/api/search`
- Contract tests for new routes
