# Subnet Dashboard Shared Workspace

**Last updated:** 2026-07-13

## Repo
- `cryptoreporthub/subnet-dashboard`

## Where to Look
1. **Board:** `cursor-agents-communication/board.md` — current phase, ownership, PRs
2. **Master plan:** `master-plan-merged.md` — phase order and sequencing rules
3. **Model guide:** `cursor-agents-communication/model-guide.md` — Composer implements; Grok-fast audits
4. **Ditto handoff:** `cursor-agents-communication/ditto-mno-handoff.md`
5. **Extended plan:** `docs/master-plan-merged.md` — contracts and M/N/O detail

## Workspace Ready When
The shared workspace is **ready for agents** once `board.md` status matches `main` (SHA, merged phases, active tracks).

**Current:** `main` @ `fbf0f27` · J/H/K/H-full/L merged · **Agents A + B idle** · **Ditto: create M/N/O plans**

## Ready for Ditto ✅

Both Cursor agents are idle and unblocked for planning:

| Agent | Phase work | Status |
|-------|------------|--------|
| **Agent A** | H-full, optional lane | ✅ Done — idle |
| **Agent B** | L signals & alerts | ✅ Done (#115 + #133) — idle |

**Ditto action:** Author M/N/O assignment plans per `ditto-mno-handoff.md`.  
**User gate:** M/N/O require explicit approval before agents start.

## Handoff Status

| Agent | Status | Next action |
|-------|--------|-------------|
| **Agent A** | Idle | Await Ditto M/N/O plan |
| **Agent B** | Idle | Await Ditto assignment |
| **Ditto** | **Create plans** | `ditto-mno-handoff.md` |

## Conflict Surface
- `server.py` — coordinate if both agents have open PRs; second merger rebases.
