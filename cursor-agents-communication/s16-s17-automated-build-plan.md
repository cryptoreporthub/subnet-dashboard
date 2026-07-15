# §16 + §17 — Automated Build Plan

**Status:** ✅ APPROVED + IN PROGRESS 2026-07-15 · human approved · **`GATE_S16` CLEAR**  
**main baseline:** `c4fe983` (#247 S1 bands; §16.1–16.3 done)  
**Specs:** `gameplan-phase-16.md` · `gameplan-beyond-16.md`  
**Prompts:** `s16-s17-start-prompts.md`

**I am Agent A (`-843d`).** Agent B (`-e78a`) gets the B queue below.

---

## Roles

| Who | Owns | Does not touch |
|-----|------|----------------|
| **A** (`-843d`) | §16 all · S1 bands **API** · S2 magnitude · F1–F6 **engines/routes** · board/STATUS after each merge | `templates/*`, `static/*` (except CONTRACT-only if forced) |
| **B** (`-e78a`) | S3 badge · S4 whales/indicators depth · **all U\*** · F\* **UI** · band display | `internal/learning/*`, `internal/council/grading.py`, `fly.toml` secrets |
| **Human** | **F7** custom domain DNS/certs · Telegram/email creds for F2/F6 | — |
| **Ditto** | Gate approve / spot-check trust metrics (not day-to-day QB) | Implementation |

**Conflict surface only:** `server.py` `include_router` + `tests/test_endpoint_contract.py` — rebase before merge if both open.

---

## Automation contract (every slice)

1. Branch: `cursor/<slice-slug>-42f7` (A) or `cursor/<slice-slug>-e78a` (B) off **latest `main`**
2. Read this file + `board.md` + `STATUS.md` first; obey **WAIT FOR** gates
3. Model: Composer 2.5 build · Grok slow+**medium** only if slice marks DESIGN — **HARD RULE:** Grok returns a short structured LOCK only; Composer writes any plan markdown and then builds (`model-guide.md`)
4. Ponytail: minimal diff; no new deps unless listed; no `data/*.json` commits
5. Test: `.venv/bin/pytest` on listed tests + `tests/test_endpoint_contract.py` if routes change
6. PR: push → ready for review → **merge when CI green** (user standing: auto-merge OK)
7. After merge: update `board.md` + `STATUS.md` one-line; `save_memory` STATUS with `main=<sha>`
8. **Auto-continue** to next slice in *your* queue when gate is clear — do not wait for chat
9. Do **not** edit this plan file mid-build unless a gate fails and needs a one-line fix note
10. Never revert #221/#223/#224/#225/#226/#227/#228/#232/#234/#237/#241 or Step 0
11. **No Plan mode every slice** — use the approved auto-plan; Grok-lock only when DESIGN-marked or path ambiguous

**Human-only (agents skip):** F7 custom domain.

---

## Global order (waves)

| Wave | Gate name | What must be on `main` | Then |
|------|-----------|------------------------|------|
| **0** | — | — | A: 16.1 → 16.2 → 16.3 |
| **1** | `GATE_S16` | §16 COMPLETE | A: S1 → S2 · B: S4 → S3 (B may start S4 when GATE_S16) |
| **2** | `GATE_S_CORE` | S1+S2+S3 on main | A: F1 → F2 · B: U1 → U2 (parallel) |
| **3** | `GATE_HABIT` | F1+F2+U1 on main | A: F3 · B: U3 → U4 + F1/F2 UI polish if needed |
| **4** | `GATE_ACCOUNT` | F3 on main | A: F4 → F5 → F6 · B: F3 UI → F4 template → F5 chat UI |
| **any** | — | — | Human F7 anytime |

---

## Agent A queue (auto)

### A1 — 16.1 Fill outcome gaps ← **HIT BUILD HERE (after approve)**

| | |
|--|--|
| **Goal** | Resolvable scenario blanks filled; leftovers explicit unresolvable |
| **Files** | `internal/learning/scenario_outcomes.py`, `tests/test_scenario_memory.py`; touch `prediction_loop.py` only if `scenario_id` still dropped |
| **AC** | Test: backfill clears pending on fixture; stats expose `outcomes_pending` / unresolvable |
| **PR** | `§16.1: finish scenario outcome backfill` |
| **Next** | A2 |

### A2 — 16.2 Gated `hybrid_score`

| | |
|--|--|
| **DESIGN** | Grok slow+medium: lock `scale` + reuse `MIN_RESOLVED_SAMPLE=30`; document in PR |
| **Goal** | `hybrid_score()` returns float iff n≥min_sample else `None` + reason `"not_enough_data"` |
| **Files** | `internal/council/grading.py`, `tests/test_hybrid_score.py` (new, small) |
| **AC** | Below gate → None; above → float in [0,1]; no fake zero |
| **PR** | `§16.2: data-gated hybrid_score` |
| **Next** | A3 |

### A3 — 16.3 Re-measure

| | |
|--|--|
| **Goal** | Prod/backtest snapshot vs Phase P 53.5% |
| **Files** | `docs/phase-16-trust-gap-snapshot.md`, board/STATUS, run `./scripts/verify_prod.sh` |
| **AC** | Snapshot committed; STATUS: **§16 COMPLETE**; set board gate `GATE_S16` |
| **PR** | `§16.3: trust-gap snapshot + GATE_S16` |
| **Next** | A4 (after own merge) |

### A4 — S1 Conviction bands API

| | |
|--|--|
| **Goal** | `band ∈ {high,medium,low}` or null+reason from agreement + hit-rate; cold-start null |
| **Files** | New thin `internal/council/conviction_bands.py` (or under learning); expose on existing pick/status JSON — **prefer extend** `/api/council` or learning stats, avoid new route unless needed; CONTRACT if new |
| **AC** | Unit test cold-start + high/med/low; never invent medium to look busy |
| **PR** | `§17.S1: conviction bands API` |
| **Next** | A5 |

### A5 — S2 Signal-derived magnitude

| | |
|--|--|
| **Goal** | New predictions: no confidence-proxy `_predicted_pct_from_pick`; tag `magnitude_source` |
| **Files** | `internal/learning/prediction_loop.py`, tests for create path |
| **AC** | New rows non-proxy; test asserts proxy unused on create |
| **PR** | `§17.S2: signal-derived predicted_pct` |
| **Next** | Wait `GATE_S_CORE` (B must merge S3) then A6 |

### A6 — F1 Watchlist API

| | |
|--|--|
| **Goal** | Pin netuids (local JSON under `data/` or session — prefer server JSON file, gitignored pattern) |
| **Files** | `internal/watchlist/*` routes; CONTRACT; no commit of live data |
| **AC** | GET/PUT watchlist 200; empty OK |
| **PR** | `§17.F1: watchlist API` |
| **Next** | A7 |

### A7 — F2 Alert delivery

| | |
|--|--|
| **Goal** | O1 → real notify (Telegram and/or email) behind flags; watchlist-aware if trivial |
| **Files** | `internal/conviction_alerts/*`; env-gated; skip live send in CI |
| **AC** | Dry-run/test path; idempotent; flag off = no send |
| **PR** | `§17.F2: conviction alert delivery` |
| **Next** | Wait `GATE_HABIT` then A8 |

### A8 — F3 Paper portfolio engine

| | |
|--|--|
| **Goal** | Follow resolved council picks; P&L vs hold TAO; §16 grading only |
| **Files** | `internal/portfolio/*` or under learning; GET status API |
| **AC** | Empty or real resolved P&L; no fake fills |
| **PR** | `§17.F3: paper portfolio engine` |
| **Next** | Wait `GATE_ACCOUNT` then A9 |

### A9 — F4 Weekly letter generator

| | |
|--|--|
| **Goal** | Markdown digest: top pick, win rate, ≤3 scenarios |
| **Files** | `internal/analytics/letter.py` or learning; GET `/api/letter/weekly` |
| **AC** | Honest empty if no data; CONTRACT |
| **PR** | `§17.F4: weekly letter API` |
| **Next** | A10 |

### A10 — F5 Streaming chat

| | |
|--|--|
| **Goal** | Streaming/chunked `POST /api/simivision/chat`; XSS-safe |
| **Files** | chat route + tests; no Flask |
| **AC** | Stream or chunk works in TestClient; CONTRACT updated if shape changes |
| **PR** | `§17.F5: streaming SimiVision chat` |
| **Next** | A11 |

### A11 — F6 Live message-intel

| | |
|--|--|
| **Goal** | Listener path healthy; API non-empty when creds else honest-empty |
| **Files** | `internal/message_intel/*`; no secrets in repo |
| **AC** | Tests with mocks; prod verify note in PR if creds absent |
| **PR** | `§17.F6: live message-intel hardening` |
| **Next** | DONE (A). Optional S5 Discord later — out of auto queue |

---

## Agent B queue (auto)

**Idle until `GATE_S16` on board/STATUS.** Then auto-continue.

### B1 — S4 Whale / rugger / indicator depth ← **B HIT BUILD HERE after GATE_S16**

| | |
|--|--|
| **Goal** | Existing CONTRACT routes: real summary or explicit empty (no decorative zeros) |
| **Files** | `internal/whales/*`, `internal/ruggers/*`, `internal/indicators/*`, tests |
| **AC** | One check per family for empty-vs-real |
| **PR** | `§17.S4: honest whale/rugger/indicator payloads` |
| **Next** | B2 |

### B2 — S3 One enrichment badge

| | |
|--|--|
| **Goal** | **Pick whale flow first** (lock); badge for home/band context; honest-empty if down |
| **Files** | Small helper + expose field on council/home JSON B already consumes; templates later in U1 |
| **AC** | Badge object `{label, status: live|empty, reason?}` |
| **PR** | `§17.S3: whale enrichment badge` |
| **Next** | After merge, help clear `GATE_S_CORE` if A S1+S2 done; then B3 |

### B3 — U1 Single-job home

| | |
|--|--|
| **WAIT FOR** | `GATE_S_CORE` (needs bands + badge fields) |
| **Goal** | First viewport = pick + band + one-line why + CTA; cockpit → Pro/below |
| **Files** | `templates/*`, `static/css/*`, `static/js/*` — preserve brand; no new panel IDs |
| **AC** | Brand-test; no hero card sprawl; mobile OK |
| **PR** | `§17.U1: single-job home` |
| **Next** | B4 |

### B4 — U2 Story strip

| | |
|--|--|
| **Goal** | Timeline last N picks right/wrong from §16 outcomes |
| **Files** | templates/partials + JS; consume learning/scenario stats |
| **AC** | Real outcomes or honest empty |
| **PR** | `§17.U2: pick story strip` |
| **Next** | B5 (may parallel A F1/F2) |

### B5 — F1/F2 UI (watchlist + alerts)

| | |
|--|--|
| **WAIT FOR** | A F1+F2 APIs on main (`GATE_HABIT` partial OK if stubs documented) |
| **Goal** | Pin UI + alert CTA on home |
| **Files** | templates/static only |
| **AC** | Works against live API or honest disabled state |
| **PR** | `§17.F1-F2: watchlist + alert UI` |
| **Next** | B6 |

### B6 — U3 Polish + predictive framing

| | |
|--|--|
| **Goal** | Phase-2 CONDITIONALs; predictive tense; hybrid or “not enough data yet” |
| **Files** | CSS/templates; `docs/premium-dashboard-redesign.md` |
| **AC** | Grok medium sign-off note in PR or waiver |
| **PR** | `§17.U3: polish + predictive framing` |
| **Next** | B7 |

### B7 — U4 Light enhance

| | |
|--|--|
| **Goal** | One home path without full reload (SSE/htmx) |
| **Files** | static/js + minimal template |
| **AC** | Documented path; a11y preserved |
| **PR** | `§17.U4: home progressive enhance` |
| **Next** | B8 |

### B8 — F3 Paper portfolio UI

| | |
|--|--|
| **WAIT FOR** | `GATE_ACCOUNT` |
| **Goal** | Render P&L vs hold TAO |
| **Files** | templates/static |
| **AC** | Empty or real; no fake |
| **PR** | `§17.F3: paper portfolio UI` |
| **Next** | B9 |

### B9 — F4 Letter template

| | |
|--|--|
| **Goal** | Render weekly letter markdown/HTML |
| **Files** | templates |
| **PR** | `§17.F4: weekly letter UI` |
| **Next** | B10 |

### B10 — F5 Chat stream UI

| | |
|--|--|
| **Goal** | Consume streaming chat; `textContent` only |
| **Files** | static/js chat |
| **PR** | `§17.F5: streaming chat UI` |
| **Next** | B11 optional |

### B11 — U5 Launch surface (if F7 done)

| | |
|--|--|
| **WAIT FOR** | Human F7 |
| **Goal** | Host/brand polish on custom domain |
| **PR** | `§17.U5: custom domain launch polish` |
| **Next** | DONE (B) |

---

## Done criteria (phase)

- [ ] `GATE_S16` · `GATE_S_CORE` · `GATE_HABIT` · `GATE_ACCOUNT` all cleared on board
- [ ] A1–A11 and B1–B10 merged (B11 optional)
- [ ] `./scripts/verify_prod.sh` green after last deploy
- [ ] No fake bands/scores/badges

---

## Review checklist

- [x] Auto plan approved; Build started
- [x] Agent A completed §16 (A1–A3) + S1 bands (A4/#247)
- [x] `GATE_S16` clear — Agent B starts **B1**
- [ ] F7 DNS stays human
- [x] Ditto = gate/spot-check only
