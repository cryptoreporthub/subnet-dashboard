# Ditto Handoff — Phase L planning request

**Repo:** https://github.com/cryptoreporthub/subnet-dashboard  
**main:** `24333f8` (as of 2026-07-12)  
**Status:** Cursor Agents A + B are **ready for Ditto to author the next phase plans**

---

## Request to Ditto

Please create **copy-paste assignment plans** for:

1. **Agent B (`-e78a`)** — Phase **L** slices 2–4 (active track)
2. **Agent A (`-843d`)** — idle / support (optional PR #110 only if needed)

Include per-slice: scope, owned paths, model choice (Composer vs Grok — see model guide), acceptance criteria, and merge order.

---

## Canonical file index (read from GitHub — not Ditto artifacts)

| # | Path | Purpose |
|---|------|---------|
| 1 | `cursor-agents-communication/board.md` | Live STATUS, gates, PRs, ownership |
| 2 | `cursor-agents-communication/model-guide.md` | **Composer vs Grok** — when to switch models per phase |
| 3 | `cursor-agents-communication/shared-workspace.md` | Handoff order, workspace ready rules |
| 4 | `master-plan-merged.md` | Short phase order at repo root |
| 5 | `docs/master-plan-merged.md` | Extended contracts + Phase L spec (§9) |
| 6 | `cursor-agents-communication/phase-h-subnet-grouping-audit.md` | Optional lane (done) |

**Model guide URL:**  
https://github.com/cryptoreporthub/subnet-dashboard/blob/main/cursor-agents-communication/model-guide.md

---

## Phase state on `main`

| Phase | Status |
|-------|--------|
| J, H-thin, K, H-full (#120), optional lane (#125) | ✅ merged |
| `/api/top-pick/hour` shape fix (#127) | ✅ merged + deployed Fly |
| Model guide (#122) | ✅ merged — `cursor-agents-communication/model-guide.md` |
| **L** | 🟢 **ACTIVE** — Agent B, PR #115 slice 1 done |

---

## Phase L — what Ditto should plan

**Owner:** Agent B (`-e78a`)  
**Branch:** `cursor/phase-l-signal-pipeline-b061` (PR #115)  
**Done:** slice 1 — `GET /api/signals`, `/api/signals/summary`, `data/signals.json`

**Remaining (plan these):**

| Slice | Scope | Model (per model-guide) |
|-------|--------|-------------------------|
| 2 | `GET/POST /api/alerts` | Composer |
| 3 | `/ws/signals` WebSocket | **Grok design first**, then Composer |
| 4 | Rules engine (SELL > HOT, dedup) | **Grok design first**, then Composer |

**Before slice 3:** Grok read-only audit of PR #113 vs #115 (avoid duplicate work).

**Agent A:** idle unless B needs trigger hooks or user requests PR #110 backend context.

---

## Model guide summary (full doc in repo)

- **Default:** Composer for implementation
- **Grok** (`grok-4.5-fast-xhigh` / `grok-4.5-xhigh`) for: L WebSocket/rules design, audits, M/N/O kickoff, past-phase reviews (J, H-full, K)
- See `cursor-agents-communication/model-guide.md` §4–§6

---

## Non-negotiables for plans

- Honest-empty > fake data
- Agent B: `internal/signals/*`, `server.py` context only — **no** `templates/*` / `static/*`
- Agent A: `templates/*`, `static/*` only when explicitly tasked
- Add new routes to `tests/test_endpoint_contract.py`
- Single server entrypoint: `server:app`
