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

**Current:** `main` @ `24333f8` · J/H-thin/K/H-full/lane/model-guide merged · **L active** (Agent B slices 2–4).

## Ready for Ditto
Cursor Agents A + B are ready for **Ditto to create Phase L assignment plans**.  
See `cursor-agents-communication/ditto-phase-l-handoff.md`.

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
| **Agent A** | H-full + lane done | Idle — see Ditto plan when published |
| **Agent B** | Slice 1 done | **Awaiting Ditto Phase L slices 2–4 plan**, then PR #115 |
| **Ditto** | — | **Create next assignment plans** — see `ditto-phase-l-handoff.md` |

## Conflict Surface
- `server.py` — if both agents have open PRs, second merger rebases.
