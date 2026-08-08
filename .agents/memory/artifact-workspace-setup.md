---
name: Artifact pnpm workspace setup
description: How the artifacts/* packages are wired so cross-artifact workspace deps (e.g. mockup-sandbox → @workspace/smoke) resolve and `pnpm --filter` commands work.
---

The `artifacts/smoke` (design-system) and `artifacts/mockup-sandbox` packages link via
`workspace:*`, and their workflow commands run `pnpm --filter @workspace/<ds> ...` from the repo root.

**Rule:** the repo needs a root `pnpm-workspace.yaml` (`packages: [artifacts/*]`). Without it,
`pnpm install` at the root fails (`ERR_PNPM_NO_PKG_MANIFEST`) and installing inside an artifact that
depends on another package fails with `ERR_PNPM_WORKSPACE_PKG_NOT_FOUND`. Adding the workspace file
makes `pnpm install` (run from repo root) resolve both projects and link `@workspace/smoke` into the
sandbox's `node_modules/@workspace/`.

**Why:** `workspace:*` and `--filter` only resolve when pnpm can see a workspace root listing the
packages. The root has no package.json of its own — a bare `pnpm-workspace.yaml` is sufficient.

**How to apply:** when wiring a design-system dependency into the mockup sandbox (or any
cross-artifact dep), add the root `pnpm-workspace.yaml`, add `"@workspace/<ds-slug>": "workspace:*"`
to the consuming artifact's `devDependencies`, then `pnpm install` from the repo root and restart the
affected preview workflow.
