# Deploy vehicle — main `44bddf11` (#1427 Fix 3 status probe / #1395)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled).

## What this deploys

Main HEAD at label time (squash-merge of [#1427](https://github.com/cryptoreporthub/subnet-dashboard/pull/1427)):

```
44bddf11643556bf8aa6f4ff2a17664b7338bef0
```

#1395 Fix 3: Bittensor integration status probe via `chain_price` RPC endpoints when
`BITTENSOR_RPC_URL` unset; shared `chain_getBlockHash` per status build for duplicate URLs;
`recorder_state()` exposes `provider_served` and per-provider `cooldown_remaining_s`.

`CHAIN_PRICE_FORWARD_RECORD` remains **off**.

## Guard contract

Per `.github/workflows/fly.yml`, merged docs-only vehicle under
`docs/deploy-vehicles/*` resolves `ref=refs/heads/main`.

This file is the only change in the vehicle PR.

## Post-deploy gate

- `GET /version` == full SHA above (plus this vehicle doc commit after merge)
- `GET /health` 200

## Authorization

Joshua GO deploy 2026-10-16: ship main `44bddf11` (#1427 Fix 3) to Fly prod.

## Receipt

| Field | Value |
|-------|-------|
| Fly workflow run | _(fill after deploy)_ |
| `/version` | _(fill after deploy)_ |
| `/health` | _(fill after deploy)_ |
