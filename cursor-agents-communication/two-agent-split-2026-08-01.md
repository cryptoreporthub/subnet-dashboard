# Two-agent split — 2026-08-01

**Purpose:** One place to hand off **two agents with different objectives** without file fights.

| Agent | Doc | Objective | Slice type | PR / plan |
|-------|-----|-----------|------------|-----------|
| **L** — Learning loop | `handoff-agent-l-learning-loop-2026-08-01.md` | Merge closed-loop PRs + Phase C mindmap *display* wiring | **MECHANICAL** | #722 · #719–#721 |
| **H** — Hero + mindmap | `handoff-agent-h-hero-mindmap-2026-08-01.md` | Hero B→A + DESIGN-HEAVY mindmap visual/audit | **DESIGN-HEAVY** | #723 · `hero-mindmap-sprint-plan.md` |

**Shared model canon:** `model-guide.md` § “Exactly ONE Sonnet gate per slice” (lands via #722 if not on `main` yet). Do not invent a competing pipeline.

**Global merge order:**

```text
1. #722  (docs: model-guide + Agent L handoff)   — if not merged
2. #719  soul_map cache
3. #720  Judges confidence weights
4. #721  Telegram author reliability
5. Agent L Phase C PR(s)
6. Agent H Task 1 / Task 2 PRs
```

**Human:** Merge product PRs in GitHub UI. After each: babysit Fly + `/health`.

**Do not** run both agents editing `mindmap_graph.js` / `panel_summaries.py` / `mindmap_aggregator.py` in parallel — Agent L Phase C first, then Agent H rebases.
