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
- **Optional lane (when ready):** per-subnet grouping/collapse — UI only; see audit doc below.

## Agent B
- Backend / L real-time signals & alerts.
- Focus on signal pipeline, alerts API, and backend test coverage.
- Keep backend changes minimal and compatible.
- **Optional lane (done):** data-flow audit for per-subnet grouping — frontend-only verdict + `netuid` alias.

## Optional Lane — Per-subnet grouping / collapse

| Step | Owner | Status |
|---|---|---|
| Data-flow audit + edge-case checklist | Agent B | **Done** |
| Premium UI grouping/collapse | Agent Ave | **Pending** |

- **Doc:** `cursor-agents-communication/phase-h-subnet-grouping-audit.md`
- **Branch/PR:** `cursor/shared-agent-workspace-4e98` → PR #123
- **Verdict:** frontend-only; join key `netuid ?? id`; 12-card cockpit grid stays flat

## Handoff Status
- **Ready for Ave (H-full):** J and K are on `main`. H-full branches exist on origin; pick `cursor/phase-h-full-premium-ac2c` or audit open PRs before new work.
- **Ready for B (L) after Ave handoff:** Slice 1 complete on `cursor/phase-l-signal-pipeline-b061` (PR #115 draft). Slices 2–4 remain (alerts, WebSocket, server-side Jinja context).
- **Pending:** User merge of H-full and L PRs.
