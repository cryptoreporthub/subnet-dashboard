---
cursor:
  subagentId: "bc-2b73b904-2901-50eb-9140-0a0daddb3cc1"
---

# Scoring caps — verdicts (updated after profile)

**Prod commit (deploy):** `ef234c95` · **Hoist on prod:** **No** · **Draft fixes:** `cursor/scoring-profile-2b73`

| Cap / control | Verdict | Data |
|---------------|---------|------|
| `TOP_SCORING_UNIVERSE` (20) web | **Replace** with snapshot reads (draft) | 127×1.44 s ≈ 183 s if sync scoring returns |
| `SCORE_SNAPSHOT_MAX_SUBNETS` (40) | **Keep** until prod proves full N | Build 57.7 s/40; hoist+parallel may cut ~30–50% but not to full 127 without measurement |
| Telegram / scenario **hoist** | **Ship** (draft) before raising cap | 40×50 ms = 2.06 s simulated; Ditto 805 ms → ~32 s of 57.7 s |
| `SCORE_SNAPSHOT_SCORE_WORKERS` | **Ship** default 4 | Local 128-name wall 0.068→0.061 s (thin); prod win TBD |
| `PICK_SCHEDULER_UNIVERSE_CAP` | **Keep** | Scheduler still scores until snapshot-only pick |
| `JUDGES_SCORING_UNIVERSE` | **Keep** | Hydration guard |
| Handler 8 s timeouts | **Keep** | Even post-hoist ~0.65 s/name × 127 ≈ 83 s background |
| Finney RPC fan-out | **Do not** without price contract | Blockmachine-only on OHLCV today |

## Headline

**Caps are not unnecessary on prod today.** Missing batch hoist explains a **large fraction** of 1.44 s/name; local 0.0005 s/name is a **falsified** proxy. After draft lands: re-measure prod `build_wall_seconds`, RSS, `coverage_complete`, then trial **80 → 127** cap with read-only metrics gate above.

## Read-only prod proof for raising cap=40

`GET /metrics`: `coverage_complete=1`, `build_wall_seconds < 480×(40/N)`, RSS < 900MB, stable `rate_limited` counter during cycle.
