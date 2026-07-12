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
- **Ave** = frontend / H-full premium cockpit (+ optional per-subnet grouping/collapse UI lane)
- **B** = backend / L real-time signals & alerts (+ optional lane data-flow audit)

## Optional Lane — Per-subnet grouping / collapse (H-full)

Parallel workstream inside H-full; does **not** block L.

| Owner | Task | Status |
|---|---|---|
| **Agent B** | Data-flow audit: confirm frontend-only grouping, edge cases, minimal compatibility | **Done** @ `dcb94da` on `cursor/shared-agent-workspace-4e98` (PR #123) |
| **Agent Ave** | UI: collapsible per-subnet groups in premium cockpit | **Not started** (unblocked — audit complete) |

**Verdict (Agent B):** Grouping/collapse is **frontend-only**. Bucket flat per-subnet lists by `netuid ?? id`. Do **not** group the 12-card `cockpit_sections` grid.

**Artifacts:**
- Audit doc: `cursor-agents-communication/phase-h-subnet-grouping-audit.md`
- Tiny fix: additive `netuid` alias on `/api/registry` and `/api/subnets` (`server.py`)
- Join key for Ave: `subnetKey(row) = row.netuid ?? row.id`

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
