# Loop-engineering adoption plan (optional)

**Source:** [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering)  
**Scope:** Operating patterns only — **not** a replacement for the trading learning loop (`internal/learning/`, `resolver.py`).  
**Status:** Planned optional slices — **not started** until user/Ditto approves.

---

## Why adopt anything?

That repo is about **how AI agents run reliably** (schedule, state, verify, budget). SimiVision already has the trading loop; we lack explicit **ops hygiene** for:

- Multi-agent coordination (A / B / Ditto)
- Learning-loop health visibility
- Drift between docs and reality

Borrow ideas, not the npm CLIs wholesale.

---

## Slice A — Agent ops (Agent B + Ditto)

**Maps to:** `board.md`, `model-guide.md`, `shared-workspace.md`

| Item | Action | Acceptance |
|------|--------|------------|
| **LOOP.md** | New file: cadence table (who runs what, when, L1/L2/L3) | Agents boot from board + LOOP |
| **Loop Ready audit** | One-time `npx @cobusgreyling/loop-audit cursor-agents-communication/`; fix gaps ≥ score 70 | Audit output saved in repo or Ditto |
| **L1 → L2 → L3** | Document in model-guide: L1 report-only → L2 assisted PR → L3 unattended (low-risk only) | model-guide §6 updated |
| **Failure modes** | `docs/agent-loop-failure-modes.md` — stale board, dual PR conflict, Grok/Composer drift | Linked from board |
| **Token budget** | Per-phase Grok-fast caps in model-guide (already partial) | Explicit table |

**Owner:** Agent B (docs) · **Grok-fast:** audit pass before merge  
**Does not touch:** resolver, grading, templates (unless LOOP references only)

---

## Slice B — Learning loop health (Agent A)

**Maps to:** `resolver_scheduler.py`, `predictions.json`, judge portfolios

| Item | Action | Acceptance |
|------|--------|------------|
| **Health endpoint** | Extend `GET /api/learning/stats` or add `/api/learning/health` | Returns: pending count, oldest pending age, last resolver cycle, watchdog flags |
| **Ledger drift check** | Compare prediction outcomes vs judge portfolio for same `prediction_id` | Drift → log + optional Phase L alert type `ledger_drift` |
| **Cockpit card** | Honest-empty health strip on learning section | Shows live metrics or explicit empty |
| **Circuit breaker** | Env cap: max weight delta per 24h (optional) | Document in sciweave binding; default off |

**Owner:** Agent A · **Grok-fast:** sign-off on drift rules  
**Does not touch:** grading constants without sciweave review

---

## Slice C — Scheduled ops (future, low priority)

| Item | Action |
|------|--------|
| Nightly board ↔ `main` SHA sync agent | Cloud agent or GH Action |
| Weekly `loop-audit` on agent comms folder | CI optional gate (report-only) |

Defer until Slices A–B ship.

---

## What we explicitly skip

- Embedding `loop-init` / `loop-context` npm tools in the Python app
- Renaming SimiVision to match loop-engineering branding
- Treating loop-engineering as the prediction/resolver implementation
- L3 unattended merges on resolver/grading/calibration paths

---

## Suggested order

1. **Slice A** (1 PR, docs-only) — lowest risk, helps Ditto + agents immediately  
2. **Slice B** (1–2 PRs, backend + small UI) — operator value  
3. **Slice C** — only if ops pain persists

---

## Ditto prompt (copy-paste)

> Read `cursor-agents-communication/loop-engineering-adoption-plan.md`. Author assignment slices A and B with acceptance criteria. Agent A owns Slice B; Agent B owns Slice A. Grok-fast audit before merge. User approval required before implementation.

---

## References

- External: https://github.com/cobusgreyling/loop-engineering  
- Internal trading loop: `internal/learning/prediction_loop.py`, `internal/council/resolver.py`  
- Phase J binding: `docs/sciweave-answers-phase-j.md`  
- Agent model policy: `cursor-agents-communication/model-guide.md`
