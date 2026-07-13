# Subnet Dashboard Master Plan

**Last updated:** 2026-07-13  
**main:** `fbf0f27`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Agent boot files
1. `cursor-agents-communication/board.md`
2. `cursor-agents-communication/model-guide.md` — **Composer vs Grok per phase**
3. `cursor-agents-communication/shared-workspace.md`
4. `cursor-agents-communication/ditto-mno-handoff.md` — Ditto M/N/O planning request

## Phase Order
1. **J** → Accuracy fix + tests
2. **H-full** → Premium UI cockpit restoration
3. **K** → CI quality gates
4. **L** → Real-time signals & alerts

> **H-thin** (PR #104) partial shell on `main`. **H-full** complete (PR #120). Optional lane (PR #125).

## Completion Snapshot (`main` @ `fbf0f27`)
| Phase | Status |
|-------|--------|
| J | ✅ merged (PR #105) |
| H-thin | ✅ merged (PR #104) |
| K | ✅ merged (PR #107) |
| H-full | ✅ merged (PR #120, hero #131) |
| H-full optional lane | ✅ merged (PR #125) |
| Model guide | ✅ merged (PR #122) |
| **L** | ✅ merged (PR #115 + **#133**) |

## Next (gated)
- **M** Social ingestion — Agent A — Ditto plan + user approval
- **N** Calibration / retrain — Agent A — Ditto plan + user approval
- **O** TAO Signal Hub — Agent A — Ditto plan + user approval

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

### L — complete (Agent B)
- PR #115 (slice 1) + PR #133 (slices 2–4 hardening) on `main` @ `fbf0f27`.
- Backend: `internal/signals/*`, alerts API, WebSocket, correlation, `build_signals_context()`.
- Grok-fast sign-off PASS.

### M/N/O — gated (Agent A)
- Awaiting Ditto assignment plans — `cursor-agents-communication/ditto-mno-handoff.md`

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
