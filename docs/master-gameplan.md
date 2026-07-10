# Master Gameplan

The canonical **Master Gameplan** lives in Ditto as artifact:

- **Path:** `docs/subnet-dashboard-reimplementation-gameplan.md`
- **Artifact ID:** `f5e49849-25d6-488f-a273-a45c6aee9b8f` (v2.0, revision 8)
- **Checklist:** `docs/master-gameplan-checklist.md`

This repo follows the 12–14 phase hybrid reimplementation plan (state vector, dual outputs,
Oracle/Echo/Pulse judges, learning loop, transparency layer, TaoDX signals).

For the full document, open the artifact in Ditto or ask an agent with Ditto MCP access to
fetch it. Do not duplicate the 800+ line plan here — Ditto is the source of truth.

## Execution priority (agent-maintained)

1. Restore FastAPI `server.py` and deploy stack
2. Fix learning loop / `dark_horse` weight skew
3. Wire transparency endpoints (`/api/pick-history`, `/transparency`)
4. Migrate stale predictions
5. TaoDX structural signals (emissions gap, miner economy)
6. **Ruggers watchlist** — track fast-flip whales (`/api/ruggers/*`, legacy)

## Whale Intelligence Service (`/api/whales`)

Full wallet tracking service with six dimensions:

| Dimension | What it tracks | Use |
|-----------|----------------|-----|
| `ruggers` | Fast flippers (6h/24h/72h) | Avoid following, exit before dump |
| `alpha_whales` | Highest win-rate + return % | Follow smart money |
| `market_movers` | Price impact on small-cap subnets | Detect who moves the market |
| `early_movers` | Entries before major moves | Leading indicator |
| `conviction_holders` | Long holds + positive outcomes | Smart money baseline |
| `rotators` | Cross-subnet capital rotation | Sector rotation signals |

Endpoints: `/api/whales/leaderboards`, `/api/whales/alerts`, `/api/whales/subnet/{netuid}/flow`
