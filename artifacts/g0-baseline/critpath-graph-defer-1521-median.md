# Critical path median — `graph-defer-1521` (`653ef795`)

Runs: 3. Close: **no** (#1058 stays open). Product round 2 of 3. Graph does **not** co-start with stats. Majority (2/3) in ≤10s budget.

| Metric | Median | Marks median (`77395892`) | Hero-first #1519 |
|--------|--------|---------------------------|------------------|
| DCL (ms) | 2733.5 | 4375.7 | 2410.8 |
| /api/learning/stats start (s) | 3.046 | 4.71 | 2.701 |
| hydrate measure (ms) | 6713 | 8613 | 10395 |
| Hero complete (s) | 9.518 | 13.881 | 14.774 |
| graph start vs stats | after settle | co-start | co-start |
| machine_state (mode) | warm | warm | warm |

Per-run dirs: `artifacts/g0-baseline/critpath-graph-defer-1521-{1,2,3}/`
Full write-up: `artifacts/g0-baseline/CRITPATH_GRAPH_DEFER.md`
