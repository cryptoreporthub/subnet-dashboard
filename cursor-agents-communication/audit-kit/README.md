# Audit kit — Subnet Dashboard (Lanes 1 & 2)

Handoff from the prior Cursor Project (`/cursor/stores/self/…`). Read this
folder before starting the population ledger or map fold-in.

## Files

| File | Purpose |
|------|---------|
| [`subnet-dashboard-audit-brief.md`](subnet-dashboard-audit-brief.md) | **Charter** — paste into the new Project's first message |
| [`f02-runtime-audit-scope.md`](f02-runtime-audit-scope.md) | F02 scope objective, twelve questions, evidence bar, §6 post-scope receipts |
| [`f-items-prior-evidence-map-2026-10-03.md`](f-items-prior-evidence-map-2026-10-03.md) | REV 2.1 F-item map — **fold-in target** for v2.7.1 settled core |
| [`f02-replit-fixlist-review-2026-10-02.md`](f02-replit-fixlist-review-2026-10-02.md) | Replit fix-list receipt (F1–F3 citations verified at pin) |
| [`stale-code-repro-registry.md`](stale-code-repro-registry.md) | Registry v1.7 — F02 baseline sweep receipts |
| [`../mission-control-log.md`](../mission-control-log.md) | Dated coordination log through 2026-10-05 |

## Production pin

`ce3d820013d45577333ac8aada8c0d9e97c54129` — matches live `/version` (PR #1319
merge, 2026-10-01). Tracked file count at pin: **1413** (`git ls-tree -r`).

## Working rules (carry into every turn)

1. **Same-turn verification** — re-fetch any file:line or config fact before
   quoting it (`git show <pin>:<path> | nl -ba`).
2. **Evidence classes** — agent agreement is not independent corroboration;
   Ditto-origin receipts stay Ditto-origin until re-verified at the pin.
3. **Copyable deliverables** — user-facing evidence in four-backtick blocks.
4. **Lane separation** — Lane 1 is read-only against the git tree; Lane 2 actions
   must match the L2.1–L2.6 envelope in the brief.
5. **Implementation boundary** — confirmed defects are audit output only.
   SQLite connection lifecycle, WAL/locking, and multi-process volume behavior
   are revisited at **implementation time**, not during the read-only audit.

## Ditto

Cross-project memories already exist (search `"Subnet Dashboard"` / F02 /
`f7f9b710`, `0083ccbd`). Mirror material decisions via `save_memory`.
