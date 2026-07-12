# Subnet Dashboard Shared Workspace

## Repo
- `cryptoreporthub/subnet-dashboard`

## Where to Look
- Board: `cursor-agents-communication/board.md`
- Master plan: `master-plan-merged.md`

## Recommended Handoff Order
1. Agent A first
2. Agent B second

## Shared Rules
- Use the board and master plan as the source of truth.
- Keep work scoped to the assigned phase.
- Avoid unrelated edits.
- Preserve existing behavior unless a phase explicitly requires change.
- Do not fabricate data or signals.

## Agent A
- Frontend / H-full premium cockpit.
- Focus on template, CSS, and UI render quality.
- Restore the premium surface while keeping honest empty states.

## Agent B
- Backend / L real-time signals & alerts.
- Focus on signal pipeline, alerts API, and backend test coverage.
- Keep backend changes minimal and compatible.

## Handoff Status
- **Ready for Agent A:** H-full branches on origin; start with `cursor/phase-h-full-premium-ac2c` (recommended).
- **Agent B:** slice 1 on PR #115; continue slices 2–4 after H-full merge unless parallel approved. Check PR #113 branch before redoing work.
- **Pending:** user merge of H-full UI, then L.
