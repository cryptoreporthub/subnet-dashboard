---
cursor:
  subagentId: "bc-3203c84d-ebb6-52d5-9525-3a12961e7605"
---

# Scoring caps — verdicts (evidence-first)

**Pin:** `ef234c95aa227c21318dd7292ad8228003495589`  
**Joshua premise:** memory fixed + better RPC → caps obsolete. **Partially false:** memory/per-name deepcopy was one term; **prod still ~1.44 s/name** and **~58 s / 40** on background build; request paths still synced until prototype.

| Cap / control | Verdict | Measured basis |
|---------------|---------|----------------|
| `TOP_SCORING_UNIVERSE` (20) on web | **Replace** — snapshot read on API; remove only after worker scores full membership | 127×1.44 s ≈ 183 s uncapped day path; prototype PR moves `/api/top-picks` off scorer |
| `SCORE_SNAPSHOT_MAX_SUBNETS` (40) | **Keep** until worker proves full-membership build < RAM/timeout budget | Prod build 57.7 s for 40; `coverage_complete=0` |
| `PICK_SCHEDULER_UNIVERSE_CAP` / `min(24,TOP)` | **Keep** for scheduler until scheduler reads snapshot only | Ditto H1 trap if uncapped before snapshot |
| `JUDGES_SCORING_UNIVERSE` (20) | **Keep** short-term; **replace** with judges cache + BG refresh (already mostly cache-first) | Hydration incident #164 |
| `SCORING_CAP_MEGA_*` heuristics | **Replace** with honest membership + snapshot ranks (not rank heuristic) | Mega exclusion changes product surface |
| `COCKPIT_PICKS_REGISTRY_CAP` (24) | **Keep** for SSE registry-only leg (display cap, not scorer) | Separate from council score |
| `SCORE_CACHE_TTL` | **Keep** as safety net after snapshot reads | Dedup only |
| Handler timeouts (8 s) | **Keep** | Cold sync scoring exceeded budget pre-prototype |
| `MAX_NETUIDS` (200) | **Keep** | Chain enumeration guard |

## Headline

1. **Do not remove universe caps in one prod flag flip** — numbers support **~170 s** class request-path cost if uncapped at current per-name prod speed.  
2. **Do** land **request-path zero scoring** (prototype draft PR), **calibration hoist** on prod, then **raise snapshot membership** with `coverage_complete` gate.  
3. **Joshua GO blockers:** deploy approval, proof of full-universe snapshot on worker, RSS under 1 GB with target N, hoist merged + per-name re-measured.

## Prototype (draft only)

Branch `cursor/scoring-off-request-path-7605`: `/api/top-picks` and weighed shortlist prefer `score_snapshots.json`; sync `score_universe` fallback only when snapshot missing (weighed).
