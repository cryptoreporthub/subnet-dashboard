# Subnet Dashboard Shared Workspace

**Last updated:** 2026-07-12

## Repo
- `cryptoreporthub/subnet-dashboard`

## Where to Look
1. **Board:** `cursor-agents-communication/board.md` — current phase, ownership, PRs
2. **Master plan:** `master-plan-merged.md` — phase order and sequencing rules
3. **Extended plan:** `docs/master-plan-merged.md` — contracts and history

## Workspace Ready When
The shared workspace is **ready for agents** once `board.md` status matches `main` (SHA, merged phases, active tracks). Read the board first on every boot.

**Current:** `main` @ `9b5546d` · J, H-thin, K merged · H-full (A) and L slice 1 (B) active.

## Recommended Handoff Order
1. **Agent A first** — H-full premium UI (`templates/*`, `static/*`)
2. **Agent B second** — Phase L signals & alerts (`internal/signals/*`, `server.py` context only)

Parallel development is OK (no file overlap). Merge order defaults to A then B unless the user approves parallel landing.

## Shared Rules
- Use the board and master plan as the source of truth.
- Keep work scoped to the assigned phase.
- Avoid unrelated edits.
- Preserve existing behavior unless a phase explicitly requires change.
- Do not fabricate data or signals.

## Agent A (`-843d`)
- **Phase:** H-full premium cockpit
- **Focus:** templates, CSS, Chart.js, UI render quality
- **Start:** `cursor/phase-h-full-premium-ac2c-42f7` (PR #120) or `cursor/phase-h-full-premium-ac2c`
- **Do not touch:** `internal/signals/*`, resolver, grading, learning weights

## Agent B (`-e78a`)
- **Phase:** L real-time signals & alerts
- **Focus:** signal pipeline, alerts API, WebSocket, backend tests
- **Start:** `cursor/phase-l-signal-pipeline-b061` (PR #115)
- **Do not touch:** `templates/*`, `static/*` (Jinja hooks via `server.py` only)

## Handoff Status
| Agent | Status | Next action |
|-------|--------|-------------|
| **Agent A** | Ready | Merge H-full UI (PR #120 recommended); then backend context PR #110 if needed |
| **Agent B** | Slice 1 done | Continue alerts + WebSocket on PR #115; audit PR #113 before redoing |
| **User** | Pending | Approve merge of H-full, then L |

## Conflict Surface
- `server.py` — if both agents have open PRs, second merger rebases.
- `tests/test_endpoint_contract.py` — add routes when porting slices.
