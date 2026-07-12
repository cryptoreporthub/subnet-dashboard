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

**Current:** `main` @ `1d50232` · J, H-thin, K, **H-full** merged · **L** active (Agent B, PR #115).

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
- **Phase:** H-full ✅ merged (PR #120)
- **Optional:** PR #110 backend context builders if needed
- **Do not touch:** `internal/signals/*`, resolver, grading, learning weights

## Agent B (`-e78a`)
- **Phase:** L real-time signals & alerts
- **Focus:** signal pipeline, alerts API, WebSocket, backend tests
- **Start:** `cursor/phase-l-signal-pipeline-b061` (PR #115)
- **Do not touch:** `templates/*`, `static/*` (Jinja hooks via `server.py` only)

## Handoff Status
| Agent | Status | Next action |
|-------|--------|-------------|
| **Agent A** | H-full merged | Optional PR #110; close superseded PR #111 |
| **Agent B** | Slice 1 done | Continue alerts + WebSocket on PR #115 |
| **User** | Pending | Merge L (PR #115) when ready |

## Conflict Surface
- `server.py` — if both agents have open PRs, second merger rebases.
- `tests/test_endpoint_contract.py` — add routes when porting slices.
