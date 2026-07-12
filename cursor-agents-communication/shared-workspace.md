# Subnet Dashboard Shared Workspace

**Last updated:** 2026-07-12

## Repo
- `cryptoreporthub/subnet-dashboard`

## Where to Look
1. **Board:** `cursor-agents-communication/board.md` — current phase, ownership, PRs
2. **Master plan:** `master-plan-merged.md` — phase order and sequencing rules
3. **Model guide:** `cursor-agents-communication/model-guide.md` — Composer vs Grok per phase; Grok review checklists
4. **Extended plan:** `docs/master-plan-merged.md` — contracts and history
5. **Optional lane audit:** `cursor-agents-communication/phase-h-subnet-grouping-audit.md`

## Workspace Ready When
The shared workspace is **ready for agents** once `board.md` status matches `main` (SHA, merged phases, active tracks). Read the board first on every boot.

**Current:** `main` @ `132bf7a` · J/H-thin/K/H-full + optional lane (#125) merged · **L active** (Agent B slices 2–4).

## Optional Lane — Per-subnet grouping / collapse

| Step | Owner | Status |
|---|---|---|
| Data-flow audit + edge-case checklist | Agent B | **Done** |
| `netuid` alias on `/api/registry` + `/api/subnets` | Agent B | **Done** |
| Premium UI grouping/collapse (`section-subnet-groups`) | Agent A | **Merged** — PR #125 |

**Verdict:** frontend-only; join key `netuid ?? id`; 12-card `cockpit_sections` grid stays flat.

## Recommended Handoff Order
1. **Agent B** — L slices 2–4 on `cursor/phase-l-signal-pipeline-b061` (PR #115)

## Agent A (`-843d`)
- **Phase:** H-full premium cockpit — **core merged** (#120)
- **Optional lane:** subnet rollup UI — **merged** (#125)

## Agent B (`-e78a`)
- **Phase:** L real-time signals & alerts
- **Start:** `cursor/phase-l-signal-pipeline-b061` (PR #115)

## Handoff Status

| Agent | Status | Next action |
|-------|--------|-------------|
| **Agent A** | H-full + lane done | Idle unless polish or PR #110 context |
| **Agent B** | Slice 1 done | **Go** — alerts + WebSocket on PR #115 |
| **User** | — | Merge PR #122 (model guide), then L when ready |

## Conflict Surface
- `server.py` — if both agents have open PRs, second merger rebases.
