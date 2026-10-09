# Deploy vehicle — main `73b2babb` (PR #1340 message-intel single-flight)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled since 2026-08-19).

## What this deploys

Main HEAD before this vehicle merges:

```
73b2babbe9f46097adc6cee982f0fab340615cb0
```

Squash merge of [#1340](https://github.com/cryptoreporthub/subnet-dashboard/pull/1340)
(parent `c8ebc29b0855d49a594da27abce66bf76bbe6446`, head `cd79f6e9e00bfa33e13bc7d8318f7bcfbc1b339e`):
message-intel single-flight TTL cache, explicit SQLite `_connection()` close,
honest degraded/stale responses on poll paths.

**Mitigation only:** reduces concurrent heavy SQLite loads and FD growth on
message-intel poll paths. No `fly.toml`, secrets, or worker scale changes.

## Guard contract

Per `.github/workflows/fly.yml`, a merged docs-only vehicle under
`docs/deploy-vehicles/*` resolves `ref=refs/heads/main`. Because this vehicle is
merged before the label is applied, the deployed SHA is the **vehicle merge SHA**
(main HEAD at label time), whose parent is `73b2babb`.

This file is the only change in this PR.

## Post-deploy gate

- `GET /version` == full main HEAD SHA at label time (vehicle merge SHA; contains `73b2babb`)
- `GET /health` == 200
- MC soak / OOM triage follow

## Authorization

Joshua GO 2026-10-09 (Cursor Project thread, pin `cd79f6e9`): squash-merge #1340 +
deploy via docs vehicle + `fly-deploy` label (not push-to-main).
