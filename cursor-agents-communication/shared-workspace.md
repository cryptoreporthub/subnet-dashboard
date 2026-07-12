# Subnet Dashboard Shared Workspace

## Repo
- `cryptoreporthub/subnet-dashboard`

## Where to Look
- Board: `cursor-agents-communication/board.md`
- Master plan: `master-plan-merged.md`

## Recommended Handoff Order
1. Ave first
2. B second

## Shared Rules
- Use the board and master plan as the source of truth.
- Keep work scoped to the assigned phase.
- Avoid unrelated edits.
- Preserve existing behavior unless a phase explicitly requires change.
- Do not fabricate data or signals.

## Agent Ave
- Frontend / H-full premium cockpit.
- Focus on template, CSS, and UI render quality.
- Restore the premium surface while keeping honest empty states.

## Agent B
- Backend / L real-time signals & alerts.
- Focus on signal pipeline, alerts API, and backend test coverage.
- Keep backend changes minimal and compatible.

## Handoff Status
- **Ready for Ave (H-full):** J and K are on `main`. H-full branches exist on origin; pick `cursor/phase-h-full-premium-ac2c` or audit open PRs before new work.
- **Ready for B (L) after Ave handoff:** Slice 1 complete on `cursor/phase-l-signal-pipeline-b061` (PR #115 draft). Slices 2–4 remain (alerts, WebSocket, server-side Jinja context).
- **Pending:** User merge of H-full and L PRs.
