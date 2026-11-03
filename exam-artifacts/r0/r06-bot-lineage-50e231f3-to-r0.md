# R0.6b — `review-gate-bot/bot/` commits: PR head `50e231f3` → R0 lineage

| SHA | Group | Local-only? | Why |
|-----|-------|-------------|-----|
| `bd529afb` | tool/guard (Replit ask dedupe) | exam lineage | Pre–PR-head harness hardening |
| `192cb3c3` | tool/guard (verdict timing) | exam lineage | |
| `c9a6400d` | config + instructions (read tool, posted:false) | exam lineage | |
| `3fd55744` | config (`reasoning_effort`) | **PR-bound fix** | Registry param name; PR head still uses `effort` |
| `80f8a295` | instructions text (blocking scope, universe 128) | **local only** | Hard-exam r2; never on PR #1522 head |
| `4002a91b` | instructions + guards (owner rules inline, reviewer state, skill table) | **local only** | Hard-exam r4 bundle |
| `798c2134` | eval harness (not `bot/` product) | local | Listed because commit touches bot paths in message |
| `3130f3b2` | instructions + post_verdict guards | **local only** | r5 exam |
| `8764c29c` | tool/guard port | **local only; never PR branch** | commit message |
| `d8751f9b` | guard audit | **local only** | |
| `4ccf5ce0` | instructions + config | **local only** | Replit tag / timing rule |
| `2982cac1` | R0 harness (instructions.ts inline, eval post-once) | R0 branch | Not for #1522 merge |
| `9c0ea1d4` | R0-REVIEW fixes | R0 branch | |

**This R0-REVIEW-2 change:** `bot/instructions.md` reset to PR head `50e231f3` (6813 B on disk); owner/reviewer blocks moved to append-only arms B/D (`bot/lib/instruction-blocks.ts`).
