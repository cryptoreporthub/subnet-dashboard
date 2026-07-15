# Subnet Dashboard Master Plan

**Last updated:** 2026-07-13T01:45:00Z  
**main:** `28e7ccd`

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

## Completion Snapshot (`main` @ `28e7ccd`)
| Phase | Status |
|-------|--------|
| J | ✅ merged (PR #105) |
| H-thin | ✅ merged (PR #104) |
| K | ✅ merged (PR #107) |
| H-full | ✅ merged (PR #120, #131) |
| H-full optional lane | ✅ merged (PR #125) |
| Model guide | ✅ merged (PR #122) |
| L | ✅ merged (PR #115, #133; UI #135) |
| **M** | ✅ merged (PR #136) |
| **N** | 🟡 APPROVED 2026-07-15 — Agent A (`-843d`) + Agent B (`-e78a`) split |
| **O** | 🟡 APPROVED 2026-07-15 — Agent A (`-843d`) + Agent B (`-e78a`) split |

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

### M — merged (Agent A)
- Social live ingestion on `main` (PR #136).
- Telegram listener, dedup, `GET /api/message-intel`, Jinja context.
- Design: `cursor-agents-communication/phase-m-design.md`

### N / O — approved (2026-07-15)
- Agent A (`-843d`) owns N2/N3/O1/O4/O5; Agent B (`-e78a`) owns N1/N4/O2/O3.
- Full spec: `cursor-agents-communication/gameplan-N-O.md`.
- Models: Composer 2.5 default build; **Grok token-save** — every Grok call starts on `grok-4.5-fast-xhigh`; escalate to `grok-4.5-xhigh` only after FAIL/CONDITIONAL (see `model-guide.md` §0/§4 + `gameplan-N-O.md` §5).

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