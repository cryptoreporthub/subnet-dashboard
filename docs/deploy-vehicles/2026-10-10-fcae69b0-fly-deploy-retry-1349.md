# Fly deploy retry — main `fcae69b0` (#1348 product + #1349 vehicle)

**Context:** [#1349](https://github.com/cryptoreporthub/subnet-dashboard/pull/1349) merged the
Deploy C vehicle but also changed `cursor-agents-communication/mission-control-log.md`.
Fly Deploy run `38050592193` failed the merged docs-only guard (non-`docs/deploy-vehicles/` path).

**This PR:** docs-only receipt to re-trigger `fly-deploy` on a merged vehicle. Product on main is
`fcae69b0` (#1348) plus vehicle doc from #1349; deploy target is **main HEAD** at label time
(`fcae69b0` — full SHA `fcae69b09053c9107afb0e2e8573fe4074e33cd7`).

**Authorization:** Joshua GO — Deploy C pipeline; retry after guard fail; no fly.toml/secrets changes.
