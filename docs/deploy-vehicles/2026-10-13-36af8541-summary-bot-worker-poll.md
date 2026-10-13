# Deploy vehicle — main `36af8541` (summary bot worker poll)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled since 2026-08-19).

## What this deploys

Main HEAD at label time:

```
36af854141f8e8c8e8f8e8f8e8f8e8f8e8f8e8f8
```

(Update to full SHA at merge: `git rev-parse main`)

Includes merge commit for:

- [#1389](https://github.com/cryptoreporthub/subnet-dashboard/pull/1389) — worker-only
  summary bot poll, 15s defer, 120s watchdog, 409 logging (supersedes open #1388
  setMyCommands slice already on main via #1390)

## Guard contract

Per `.github/workflows/fly.yml`, merged docs-only vehicle under
`docs/deploy-vehicles/*` resolves `ref=refs/heads/main`.

This file is the only change in the vehicle PR.

## Post-deploy gate

- `GET /version` == full SHA of merged main
- `GET /health` 200
- Fly logs: `Telegram summary bot polling started`
- Pending Bot API queue drains (verify offset in logs — do not SSH `getUpdates`)

## Authorization

Joshua GO deploy (2026-10-13): fly-deploy summary bot worker poll fix.
