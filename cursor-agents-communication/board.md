# Subnet Dashboard Coordination Board

## Repo
- `cryptoreporthub/subnet-dashboard`

## Source of Truth
- The board and master plan override memory, prior summaries, and informal instructions.
- Agents must read this file first.

## Current Phase Order
- J → Accuracy Fix + Tests
- H-full → Premium UI cockpit restoration
- K → CI Quality Gates
- L → Real-time signals & alerts

## Active Phase
- **H-full** (Agent A) — primary handoff; UI on origin branches, not merged to `main`.
- **L** (Agent B) — slice 1 on `cursor/phase-l-signal-pipeline-b061` (PR #115 draft); full L follows H-full merge unless user approves parallel.
- **Completed on `main` @ `9b5546d`:** J (PR #105), H-thin (PR #104), K (PR #107).

## Agent Ownership
- **Agent A** = frontend / H-full premium cockpit (`templates/*`, `static/*`, `tests/test_phase_h_ui.py`)
- **Agent B** = backend / L real-time signals & alerts (`internal/signals/*`, alerts, WebSocket; Jinja context via `server.py` only)

## Status
- H-full not on `main` yet (no Chart.js on homepage).
- H-full recommended: `cursor/phase-h-full-premium-ac2c` (20 UI tests). Alternates: `27f3`, PR #111 (`e78a`). Backend-only `843d` (PR #110) merges after UI.
- L slice 1 done: `GET /api/signals`, `/api/signals/summary`, `data/signals.json` on PR #115.
- L extended work may exist on `cursor/phase-l-signals-alerts-b061` (PR #113) — audit before duplicating.
- Blockers: user merge required for H-full and L before M/N/O.
- Conflict surface: `server.py` if both agents have open PRs; second merger rebases.

## Rules
- Stay scoped to the assigned phase.
- Do not overlap H-full and L unless explicitly approved.
- Do not modify resolver, grading, or learning-engine logic unless required for compatibility.
- Keep changes minimal and behavior-preserving.
