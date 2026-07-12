# Subnet Dashboard Master Plan

**Last updated:** 2026-07-12  
**main:** `9b5546d`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Phase Order
1. **J** → Accuracy fix + tests
2. **H-full** → Premium UI cockpit restoration
3. **K** → CI quality gates
4. **L** → Real-time signals & alerts

> **H-thin** shipped on `main` as the partial H shell (PR #104). **H-full** completes the premium cockpit (Chart.js, 13 sections).

## Completion Snapshot (`main` @ `9b5546d`)
| Phase | Status |
|-------|--------|
| J | ✅ merged (PR #105) |
| H-thin | ✅ merged (PR #104) |
| K | ✅ merged (PR #107) — gate **unblocked** |
| H-full | 🟢 active — Agent A, not merged |
| L | 🟡 slice 1 — Agent B, PR #115 draft |

## Phase Responsibilities

### J
- Accuracy fixes and test coverage.
- **Done on `main`.**

### H-full
- Restore the premium UI cockpit on the homepage.
- Frontend-heavy work only (`templates/*`, `static/*`).
- Keep the UI honest and production-safe.
- **Owner:** Agent A (`-843d`).

### K
- CI quality gates and validation checks.
- **Done on `main`.** Unblocks H-full and L.

### L
- Real-time signals and alerts.
- Backend-heavy work only (`internal/signals/*`, alerts API, WebSocket).
- **Owner:** Agent B (`-e78a`).

## Sequencing Rules
- **No overlap:** H-full and L must not share file paths. Agent A owns frontend; Agent B owns backend.
- **No overlap unless approved:** Do not merge H-full and L work into conflicting PRs without user sign-off.
- **Handoff order:** Agent A (H-full) first, Agent B (L) second for merge to `main` unless parallel is explicitly approved.
- Later phases (M/N/O) must not start until H-full and L are stable on `main`.

## Non-Negotiables
- Honest-empty > decorative summaries > 500 errors.
- Do not introduce fake live data or fabricated signals.
- Keep the dashboard minimal and behavior-preserving.

## Extended Reference
- Model selection: `cursor-agents-communication/model-guide.md`
- Full history, contracts, and phase I root-cause: `docs/master-plan-merged.md`
- UI spec: `docs/premium-dashboard-redesign.md`
- Coordination board: `cursor-agents-communication/board.md`
