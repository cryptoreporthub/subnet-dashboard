# Deploy vehicle — live subnet count fix (#1267)

| | |
|---|---|
| Vehicle type | Docs-only Fly deploy vehicle |
| Target | `refs/heads/main` (post-merge) |
| Ships | PR #1267 — `fix: derive dashboard subnet count from live universe` |

## Why a vehicle is required

Push-to-main deploys are disabled (INCIDENT 2026-08-19). The only deploy levers are
`workflow_dispatch` on `main`, or applying the exact label `fly-deploy` to a same-repo PR.

This PR is docs-only under `docs/deploy-vehicles/`, so once it is merged and labeled, the
Deploy Guard resolves `refs/heads/main` and ships the current `main` HEAD — which includes #1267.

## What this deploy ships

- `/api/stats` derives its subnet universe from the live `/api/subnets` feed instead of the
  stale `config/registry.json`.
- Explicit `active_count`, `active_count_excluding_root`, and Root/SN0 policy metadata.
- Homepage cache hydration no longer treats an empty subnet array as a valid replacement.
- Regression tests for live counts, Root exclusion, stale-registry mismatch, and genuine empty state.

## Post-deploy expectation

`/version` equals the post-merge `main` short SHA. `/api/stats` reports the live universe
(`active_count_excluding_root` == 128) rather than the stale 75-subnet registry universe.

## Non-goals

No code changes, no config or secret changes, no other workflows.
