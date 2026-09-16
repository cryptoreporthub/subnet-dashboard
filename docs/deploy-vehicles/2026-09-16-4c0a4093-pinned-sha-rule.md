# Deploy vehicle — main `4c0a4093` (agents pinned-SHA verification rule)

**Purpose:** Deploy vehicle only. This PR carries no production code. Its sole
function is to carry the exact `fly-deploy` label that triggers `fly.yml` on
merged, docs-only vehicle PRs.

## What this deploys

Main HEAD as of label time. Main was at:

```
4c0a4093292079839095250d9b0290e5832796d0
```

(merge of #1289, `docs/agents-pinned-sha-verification-rule`)

## Guard contract satisfied

Per `.github/workflows/fly.yml` at `4c0a4093` (blob `4dbdc39c9577449c14a17aa35cc2b481ac95f0a8`),
the Deploy Guard resolves the checkout ref:

- `merged: true` **and** every changed file matches `docs/deploy-vehicles/*`
  → `ref=refs/heads/main` (this PR — enables `/version == main short SHA`)
- `merged: true` with any file outside `docs/deploy-vehicles/*`
  → `GUARD FAIL`, `exit 1`, fails closed
- unmerged labeled PR → `head.sha`
- `workflow_dispatch` → `github.sha`

This file is the only changed file in this PR and lives under
`docs/deploy-vehicles/`, so the guard resolves `refs/heads/main`.

## Post-deploy gate

`GET /version` must equal the main short SHA at label time — not
`4c0a4093` if main advanced, and not this branch tip.

## Authorization

User-approved: merge AND deploy.
