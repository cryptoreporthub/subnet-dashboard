# Deploy vehicle — 2026-09-03 gate validation (docs-only fire drill)

- **Date:** 2026-09-03 / 2026-09-04 PT
- **Purpose:** Deliberate validation vehicle for the amended `fly.yml` ref-resolution gate from #1185 — no app changes.
- **Branch:** `vehicle/2026-09-03-gate-validation`
- **Base main at cut:** `6409976ab786166bab328936f1177fa8aaae58fe` (#1185 tip)

## Expected outcome (after squash-merge + `fly-deploy` label)

1. Fly Deploy checks out **`refs/heads/main`** (not this PR's head SHA).
2. Run log contains: `Resolved: merged docs-only vehicle PR #<N> → refs/heads/main`
3. Production `GET /version` `version` field equals the **post-merge main short SHA**.

## References

- Incident: PR #1182 / vehicle #1183 / Fly run [33832841118](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33832841118) — `/version` reported vehicle tip `334acc3` ≠ squash `d654aab` because pre-#1185 `fly.yml` checked out `pull_request.head.sha`.
- Fix: #1185 (`fix/fly-deploy-main-head-for-merged-vehicle`) + gate docs #1184 (`docs/deploy-vehicles/GATE.md`).

This file is the only change. Scope is docs-only under `docs/deploy-vehicles/`.
