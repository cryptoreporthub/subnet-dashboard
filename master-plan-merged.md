# Subnet Dashboard Master Plan

**Last updated:** 2026-07-12  
**main:** `24333f8`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Agent boot files
1. `cursor-agents-communication/board.md`
2. `cursor-agents-communication/model-guide.md` — **Composer vs Grok per phase**
3. `cursor-agents-communication/shared-workspace.md`
4. `cursor-agents-communication/ditto-phase-l-handoff.md` — Ditto planning request

## Phase Order
1. **J** → Accuracy fix + tests
2. **H-full** → Premium UI cockpit restoration
3. **K** → CI quality gates
4. **L** → Real-time signals & alerts

> **H-thin** (PR #104) partial shell on `main`. **H-full** complete (PR #120). Optional lane (PR #125).

## Completion Snapshot (`main` @ `24333f8`)
| Phase | Status |
|-------|--------|
| J | ✅ merged (PR #105) |
| H-thin | ✅ merged (PR #104) |
| K | ✅ merged (PR #107) |
| H-full | ✅ merged (PR #120) |
| H-full optional lane | ✅ merged (PR #125) |
| **L** | 🟢 **active** — Agent B, PR #115 |

## Model selection (Composer vs Grok)
**Canonical:** `cursor-agents-communication/model-guide.md`

| Default | Switch to Grok |
|---------|----------------|
| Composer — implementation, templates, routes, CI | L WebSocket + rules design; M/N/O kickoff; read-only audits |

Phase L: Composer slices 1–2; **Grok design before** slices 3–4 (WebSocket, rules engine).

## Phase Responsibilities

### J — done

### H-full — done (Agent A)

### K — done

### L — active (Agent B)
- Real-time signals and alerts.
- Backend: `internal/signals/*`, alerts API, WebSocket.
- **Owner:** Agent B (`-e78a`).
- **Ditto:** author slices 2–4 plans → `ditto-phase-l-handoff.md`

## Sequencing Rules
- No overlap: Agent A frontend vs Agent B backend paths.
- L stable on `main` before M/N/O.

## Non-Negotiables
- Honest-empty > decorative summaries > 500 errors.
- No fake live data or fabricated signals.

## Extended Reference
- Full history: `docs/master-plan-merged.md`
- UI spec: `docs/premium-dashboard-redesign.md`
- Board: `cursor-agents-communication/board.md`
