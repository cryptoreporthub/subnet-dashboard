# Deploy vehicle — 2026-10-10 — Deploy B (P4b + P3c)

Docs-only deploy vehicle. No code changes.

On `fly-deploy` label (post-merge), deploys `origin/main` HEAD including:

- **P4b** #1346 — loop stall guard calibration (merged `9afa6c98`)
- **P3c** #1332 — message-intel reliability (merged `b00a7f1a`)

Post-deploy gate: `GET /version` must equal **`b00a7f1a51f83de2ae7289a58fdb529072faa473`**.

**Soak 5** clock starts on this deploy anchor (≥24h per merge-soak-criteria).
