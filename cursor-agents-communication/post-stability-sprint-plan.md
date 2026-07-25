# Post-stability sprint — close the trust gap

**Status:** ACTIVE — execute one PR at a time: merge → verify prod → next  
**Updated:** 2026-07-25  
**Predecessor:** `prod-stability-plan.md` Phases 0–4 ✅ **COMPLETE** (`main` ≥ `49159d5` + #461 docs)  
**North star:** Tier‑1 surfaces show **real data or dignified Quiet within ~5s**; home answers one trader question per viewport.

---

## What just shipped (do not re-litigate)

| PR | Delivered |
|----|-----------|
| #462–#464 | Fast pump desk API, compact UI, sequential hydrate, chat context cache |
| #461 | This planning chain + STATUS pointer |

**B0-0 gate:** Met by stability Phases 0–3 (reconnect smoke, Quiet states, pump data live). **Batch 0 (B0-a…d) is unblocked.**

---

## Execution order

```text
Wave A  Verify + ops gate          ← human + script; worker scale if soak fails
  → Wave B  Batch 0 brain (B0-a…d) ← highest product trust ROI
  → Wave C  Pump parity chips      ← P5 founder + optional #455 social
  → Wave D  Chat completion        ← Phase 4 follow-up
  → Wave E  Subnet connections     ← #449 phased (API → UI → macro)
  → Wave F  Housekeeping           ← STATUS sync, stale PRs, E1 test debt (optional)
```

**Hard gate:** Do not start Wave B until Wave A prod soak passes (or worker scale is applied and soak re-run).

---

## Wave A — Verify & ops (gate)

**Branch:** `cursor/wave-a-prod-gate-d2cd` (docs + script tweaks only; ops is human)

**One command:** `./scripts/wave_a_gate.sh` runs contract tests + G0 + pump/health soak + `verify_prod.sh`.

### A1 — Automated prod gate
| Step | Command / work |
|------|----------------|
| Contract | `pytest tests/test_endpoint_contract.py tests/test_reconnect_smoke.py tests/test_prod_stability.py -q` |
| Prod script | `BASE=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh` |
| Pump soak | 5× `/api/pump-alerts` &lt;2s, `status != timeout` |
| Health soak | 10× `/health` 200 (already in `verify_prod.sh`) |

### A2 — G0 human sign-off (required)
| Step | Work |
|------|------|
| Script | `./scripts/g0_phone_qa.sh` |
| Manual 390px | Featured Call → Pump desk (Warming/Active + sparklines) → one horizon path without Pro scroll |
| Record | Note pass/fail in Ditto + tick G0 in `gameplan-pump-site-undeniable.md` |

**AC:**
- [ ] G0 script green
- [ ] Human 390px sign-off recorded
- [ ] `verify_prod.sh` completes without assert failures

### A3 — Ops escape hatch (only if A1/A2 flap)
| Condition | Action |
|-----------|--------|
| `/api/ops/readiness` or `/` wedges under normal browse | `fly scale count worker=1` (dedicated worker; web stays HTTP-only) |
| Re-run | A1 soak after scale |

**Model:** Composer (script/docs) · human (Fly ops)

---

## Wave B — Batch 0 brain presentation (B0-a → B0-d)

**Canon:** `batch0-final-merged-plan.md` + `batch0-brain-presentation-lock.md` v2.1  
**Rule:** One slice per PR; no hero stack redesign (K3-7 LOCK).

| Slice | Branch | Intent | Key files |
|-------|--------|--------|-----------|
| **B0-a** | `cursor/b0-a-living-focus-d2cd` | §27 four-beat LF; weight-nudge; no eternal Loading | `living_focus.html/js`, `council_first.css` |
| **B0-b** | `cursor/b0-b-brain-letter-d2cd` | SSR letter + Outlook; file-backed graded data | `brain_letter.*`, `internal/letter/` |
| **B0-c** | `cursor/b0-c-proof-band-d2cd` | Trust score hero; story strip; collapse letters drawer | `premium_cockpit.html`, proof band partials |
| **B0-d** | `cursor/b0-d-empty-taxonomy-d2cd` | Live/Quiet/Building; dual-judge labels; 390px QA | hydrate JS, empty copy sweep |

**Per-slice AC (all):**
- [ ] After 5s @390px prod, zero eternal Loading on Tier‑1 brain surfaces
- [ ] Quiet states dated when possible
- [ ] Contract tests green
- [ ] `g0_phone_qa.sh` still green

**Model:** Composer 2.5 default · Grok medium LOCK only if VA copy ambiguous

---

## Wave C — Pump parity chips

### C1 — P5 founder/owner chip
**Branch:** `cursor/p5-founder-chip-d2cd`  
**Intent:** TaoDX parity — owner/founder line on pump cards when registry/TaoStats has it.

| Work | Detail |
|------|--------|
| Data | `config/` or registry field + `build_alert_row` / desk row |
| UI | Chip on pump card + compact desk row (honest-empty when unknown) |
| Test | `test_pump_alert.py` fixture netuid with override |

**AC:**
- [ ] Chip shows on desk when data present; hidden when absent (no fabrication)
- [ ] 390px: chip does not wrap hero or break compact desk row

### C2 — Social conviction evidence (optional, rebase #455)
**Branch:** Rebase `cursor/social-conviction-evidence-c9f5` → `cursor/social-conviction-d2cd`  
**Intent:** Social as evidence on dossier + desk-first panel — not Tao.app breadth.

| Work | Detail |
|------|--------|
| Merge path | Rebase #455 onto `main`; resolve `cockpit_hydrate.js` / dossier conflicts |
| Honest empty | No "warming up" when Telegram ingest off |

**AC:**
- [ ] `social_crumb` on daily pick when intel exists
- [ ] Homepage social panel prioritizes desk netuid
- [ ] Empty = explicit "ingest off" copy

**Gate:** Ship C1 first unless #455 rebase is trivial (&lt;30 min conflict).

**Model:** Composer

---

## Wave D — Chat completion (Phase 4 follow-up)

**Branch:** `cursor/chat-fast-path-d2cd`  
**Predecessor:** Partial cache in #464 — full AC not met.

| Step | Work |
|------|------|
| D1 | Profile `POST /api/chat` / stream — identify remaining slow path (investigation? LLM?) |
| D2 | Defer investigation unless wallet/subnet keywords in message |
| D3 | Client: distinguish timeout vs unreachable vs partial context |
| D4 | Test: `test_chat_stability.py` + contract route timing budget |

**AC:**
- [ ] Chat responds &lt;8s p95 on prod for generic pick question (no on-chain investigation)
- [ ] Investigation path still works when keywords present, with honest timeout message

**Model:** Grok medium LOCK (scope) → Composer

---

## Wave E — Subnet connections (#449 phased)

**Do not monolith.** Three PRs max.

| Phase | Branch | Scope |
|-------|--------|-------|
| E1 | `cursor/subnet-integrations-api-d2cd` | `GET /api/subnet-integrations`, signals endpoint, contract tests |
| E2 | `cursor/subnet-integrations-ui-d2cd` | Corner badges + dossier crumbs (reuse #442 patterns) |
| E3 | `cursor/subnet-macro-overlay-d2cd` | Council macro overlay + `GET /api/ops/llm-cost` (optional) |

**AC per phase:**
- [ ] Contract green for new routes
- [ ] Honest-empty when probe fails
- [ ] No hydrate regression (run `verify_prod.sh` pump + health)

**Gate:** Start E only after Wave B-C shipped (avoid parallel hydrate load during Batch 0).

**Model:** Composer · Grok medium for macro overlay tuning only

---

## Wave F — Housekeeping (low priority, parallel OK)

| Item | Branch / action |
|------|-----------------|
| STATUS sync | Each merge updates `STATUS.md` + Ditto STATUS post |
| Close stale doc PRs | #378, #371, #374, #404 — merge or close after content absorbed |
| E1 test debt | `post-s28-backlog.md` — fix or `@pytest.mark.skip` with ticket per module |
| H1 hour-watch | `h1-hour-watch-live-lock.md` — **after B0-d** + G0 green |

**Model:** Composer fast pool for docs/chores only

---

## Verify checklist (every wave)

1. `pytest tests/test_endpoint_contract.py tests/test_reconnect_smoke.py -q`
2. `BASE=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh` (or pump + health subset if full script wedges)
3. `./scripts/g0_phone_qa.sh`
4. Browser: home loads, pump desk has data or Quiet, chat sends one message

---

## Model ladder (unchanged)

| Work | Model |
|------|-------|
| Locked slices B0 / P5 / rebase #455 | **Composer 2.5** |
| Chat scope LOCK, macro overlay | **Grok medium** → Composer |
| Novel multi-service architecture | **Opus** only if Grok medium FAILs |
| Docs / STATUS / board | **Composer fast** |

---

## Suggested first three PRs (start here)

1. **`cursor/wave-a-prod-gate-d2cd`** — tick G0 in docs; any `verify_prod.sh` fix from soak failures  
2. **`cursor/b0-a-living-focus-d2cd`** — Batch 0 slice 1  
3. **`cursor/p5-founder-chip-d2cd`** — quick pump parity win  

---

## References

- `prod-stability-plan.md` — completed Phases 0–4
- `batch0-final-merged-plan.md` — B0-a…d detail
- `gameplan-pump-site-undeniable.md` — G0, P5, design intent
- `h1-hour-watch-live-lock.md` — deferred until B0 + G0
- Open PRs: #455 (social), #449 (integrations)
