# Deploy vehicle — 2026-09-09 · main @ ec06d99

Docs-only deploy vehicle. Ships the merged-but-undeployed train:

- #1259 — SS-TG: Telegram alert on trending #1 takeover (`trend_alert.py` watcher + tests + boot wiring)
- #1260 — arm `TELEGRAM_TREND_ALERT=on` via fly-secrets.yml (secret-set job already succeeded, 00:09 UTC)

**Base deployed:** latest successful Fly deploy (pre-train).
**This vehicle deploys:** `ec06d990` (CI Smoke run SUCCESS on push).

Post-deploy verification: /health 200, `trend takeover watcher started` in logs, first tick records silent baseline (data/trend_state.json).
