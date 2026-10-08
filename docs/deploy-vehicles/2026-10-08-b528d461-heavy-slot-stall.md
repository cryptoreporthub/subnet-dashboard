# Deploy vehicle — main `b528d461` (PR #1338 heavy_job_slot stall fix)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled since 2026-08-19).

## What this deploys

Main HEAD before this vehicle merges:

```
b528d46184ae49a480ddc731b62027f30d8f85bc
```

Squash merge of [#1338](https://github.com/cryptoreporthub/subnet-dashboard/pull/1338)
(parent `5ad0047676ac31f453b7735ce3610cfe62a88ad7`, head `7a9fe4f7dbf6c0dc26f2c2af8cd2f8edc306179f`):
stop `pump_ladder` from pinning the worker's `heavy_job_slot` indefinitely.

**Mitigation only:** frees the worker's `heavy_job_slot` after a 600s
`PUMP_LADDER_BODY_STALL_SECONDS` tick-body stall so the resolver / score snapshot
can acquire it again. It does not fix the underlying stall or the web OOM.
No `fly.toml`, secrets, or `RESOLVER_*` changes.

## Guard contract

Per `.github/workflows/fly.yml`, a merged docs-only vehicle under
`docs/deploy-vehicles/*` resolves `ref=refs/heads/main`. Because this vehicle is
merged before the label is applied, the deployed SHA is the **vehicle merge SHA**
(main HEAD at label time), whose parent is `b528d461`.

This file is the only change in this PR.

## Post-deploy gate

- `GET /version` == full main HEAD SHA at label time (vehicle merge SHA; contains `b528d461`)
- `GET /health` == 200
- Fly Machines API events show the restart for machine `7841024b3712e8`
- `flyctl logs`: `heavy_job_slot` acquire/release lines with holders after boot;
  `pump_ladder` releases (`held_ms`), and any `tick_body_stalled`
- MC Axiom soak 3 follows

## Authorization

Joshua authorization (~2:25 PM PT, 2026-10-08, Cursor Project thread): "Okay. Go is authorized"
— merge #1338 + deploy via vehicle. Mission Control posted GO.
MC AC PASS at `7a9fe4f7dbf6c0dc26f2c2af8cd2f8edc306179f`.
Vehicle opened by Mission Control via `gh` (Cursor Project blocked by a CloudAgent usage limit).
