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
- **Active phase:** H-full (primary handoff). J and K are merged on `main` @ `19e0ebd`. L slice 1 is in progress on a draft branch; full L work follows H-full handoff unless explicitly approved to run in parallel.

## Agent Ownership
- **Ave** = frontend / H-full premium cockpit
- **B** = backend / L real-time signals & alerts

## Status
- `main` @ `19e0ebd`. J merged (PR #105). H-thin merged (PR #104). K merged (PR #107).
- **H-full:** UI work exists on branches; not merged to `main`. Recommended merge candidate: `cursor/phase-h-full-premium-ac2c`. Alternate: `cursor/phase-h-full-premium-27f3`. Open PRs include #111 (`e78a`).
- **L:** Slice 1 done on `cursor/phase-l-signal-pipeline-b061` (GET `/api/signals`, `/api/signals/summary`, `data/signals.json`). PR #115 draft. Remaining: alerts, WebSocket, Jinja context via `server.py` only.
- **Blockers:** User merge required for H-full and L PRs before M/N/O.
- **Conflict surface:** `server.py` if both agents have open PRs; second merger rebases.

## Rules
- Stay scoped to the assigned phase.
- Do not overlap H-full and L unless explicitly approved.
- Do not modify resolver, grading, or learning-engine logic unless required for compatibility.
- Keep changes minimal and behavior-preserving.
