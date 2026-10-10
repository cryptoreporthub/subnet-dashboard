# Deploy vehicle — 2026-10-10 — Deploy C (#1348 feed_stale watchdog)

Docs-only deploy vehicle. No code changes.

**Target main SHA:** `fcae69b09053c9107afb0e2e8573fe4074e33cd7` (`fcae69b0`)

On **`fly-deploy` label applied post-merge** to this PR (actor `cryptoreporthub`), deploys `origin/main` HEAD including:

- **#1348** — `fix(message-intel): feed_stale watchdog + listener-start backfill`
  - `_feed_stale_watchdog` with fenced early strike clears (invocation owner/gen snapshot)
  - `_listener_running_for(listener)` for correct running-state checks
  - Listener-start backfill + hardened tests (`test_message_intel_harden.py`, gap backfill, outcomes, F6)

Post-deploy gate: `GET /version` must equal **`fcae69b09053c9107afb0e2e8573fe4074e33cd7`** (or `fcae69b0` prefix).

**Trigger steps:** merge this vehicle PR → apply exact label `fly-deploy` on the merged PR (push-to-main deploy disabled per `fly.yml`).
