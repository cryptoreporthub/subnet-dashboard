# Ditto Handoff — Post Phase L (M/N/O planning)

**Repo:** https://github.com/cryptoreporthub/subnet-dashboard  
**main:** `fbf0f27` (as of 2026-07-13)  
**Status:** Cursor Agents **A + B idle** — ready for Ditto next-phase plans

---

## Request to Ditto

Phase **L** is complete. Please create **copy-paste assignment plans** for the next gated phases:

| Phase | Owner | Model (per model-guide) | Gate |
|-------|-------|-------------------------|------|
| **M** — Social ingestion | Agent A | Grok-fast design → Composer build | User approval |
| **N** — Calibration / retrain | Agent A | Grok-xhigh design → Composer build | User approval + J stable |
| **O** — TAO Signal Hub | Agent A | Grok-fast design → Composer wire | After L partial (✅) |

Include per-phase: scope, owned paths, acceptance criteria, merge order, Grok sign-off points.

**Optional (explicit task only):** Agent A frontend consumers for Phase L signals (`signals`, `alerts`, `signal_summary` in Jinja context).

---

## Canonical read order

1. `cursor-agents-communication/board.md`
2. `cursor-agents-communication/model-guide.md` — Grok-fast default for audits/sign-offs
3. `cursor-agents-communication/shared-workspace.md`
4. `master-plan-merged.md` + `docs/master-plan-merged.md` §10–12

---

## Phase L — complete on `main`

| PR | Scope |
|----|--------|
| **#115** | Slice 1 — signals pipeline |
| **#133** | Slices 2–4 hardening — alerts API, WS, correlation, Grok design docs |

**Health @ `fbf0f27`:** `GET /health` 200 · `GET /api/signals` 200 · `GET /api/alerts` 200 · Grok-fast sign-off PASS

**Design docs:** `phase-l-slice3-ws-design.md`, `phase-l-slice4-rules-design.md`, `phase-l-pr113-audit.md`

---

## Agent status

| Agent | Status | Blocked on |
|-------|--------|------------|
| **Agent A** (`-843d`) | **Idle** | Ditto M/N/O plan + user approval |
| **Agent B** (`-e78a`) | **Idle** | Ditto assignment (no open L work) |
| **Ditto** | **Action** | Author M/N/O assignment plans |

---

## Non-negotiables (unchanged)

- Honest-empty > fake data
- Agent A: `templates/*`, `static/*` when tasked
- Agent B: backend only when tasked — no UI unless explicit
- Grok: read-only design/audit; Composer implements
- M/N/O require user approval before agents start
