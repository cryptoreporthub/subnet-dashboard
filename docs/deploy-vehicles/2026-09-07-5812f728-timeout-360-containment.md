# Deploy Vehicle — RESOLVER_CYCLE_TIMEOUT_SECONDS 180→360 (containment)

Deploy vehicle for main @ `5812f728a0ba0d3a9e44e86eaf579419104abd59`
("Merge PR #1213: RESOLVER_CYCLE_TIMEOUT_SECONDS 180→360 (containment)").

Receipt path: `docs/deploy-vehicles/` (required by fly.yml docs-only guard;
`docs/vehicles/` is refused fail-closed — same correction as vehicle #1212).

## Shipped on main
- Merge commit: `5812f728a0ba0d3a9e44e86eaf579419104abd59`
- PR #1213 head: `e1b2f622cc06fc918e2661ea4b7dcd5265d35c18`
- Change: `fly.toml` `[env]` only
  - Keep Aug 28 comment; add 2026-09-07 containment comment
  - `RESOLVER_CYCLE_TIMEOUT_SECONDS` `"180"` → `"360"`

## Part A receipts (WORKER DIAG v3)
- Capture: fly-incident-logs run `34170087153`
- A1 PASS: soul_map `24,236,142` B (+0.024% vs B0 `24,230,371`); mtime `2026-09-07T23:28:28Z`
- A6 PASS: no Fly secret `RESOLVER_CYCLE_TIMEOUT_SECONDS` (fly.toml authoritative)

## Intent
CONTAINMENT ONLY — let ~250s cycles close inside 360s budget.
Kill-switch: if cycles still fail to close inside 360s → NO further bumps →
escalate to soul_map compaction (Option A).

## Post-deploy asserts
After one full cycle (~360s window):
- `total_cycle_ms` ~200k–250k, `complete=true`
- `t6`/`t7` non-null
- `enforced_budget_s=360` on `/api/predictions/resolver`
- `last_run_at` advances off `21:27:15Z`; `next_run_at` armed; no `cycle_timeout_360s`
