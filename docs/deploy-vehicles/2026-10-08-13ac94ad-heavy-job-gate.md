# Deploy vehicle — main `13ac94ad` (PR #1333 heavy job gate)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled since 2026-08-19).

## What this deploys

Main HEAD at label time:

```
13ac94adbc0e49863b891c7b3cf520a55e8401cb
```

Squash merge of [#1333](https://github.com/cryptoreporthub/subnet-dashboard/pull/1333)
— heavy_job_slot holder instrumentation + contention repro tests.

## Guard contract

Per `.github/workflows/fly.yml`, merged docs-only vehicle under
`docs/deploy-vehicles/*` resolves `ref=refs/heads/main`.

This file is the only change in this PR.

## Post-deploy gate

- `GET /version` == `13ac94adbc0e49863b891c7b3cf520a55e8401cb`
- Homepage Post-Deploy Smoke after Fly Deploy completes
- MC Axiom soak spot-check follows

## Authorization

Joshua green light 2026-10-08: merge #1333 + deploy via vehicle.
