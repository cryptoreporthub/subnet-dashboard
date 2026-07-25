# Prod stability + Ditto priorities (merged plan)

**Status:** ACTIVE — execute one PR at a time: merge → verify prod → next  
**Updated:** 2026-07-25  
**Supersedes:** ad-hoc “fix 422s” narrative (stale); aligns with `batch0-final-merged-plan.md` B0-0  
**Model ladder:** `model-guide.md` — Grok slow+medium LOCK → Composer 2.5 build; Opus only per § Model assignment below

---

## North star (from Ditto VA-00, corrected)

Tier‑1 surfaces must show **real data or dignified Quiet within ~5s**. The failure mode is **perceived death** (spinners, empty pump desk, white-screen flaps) — not missing routes.

---

## Ditto list → plan mapping

| Ditto suggestion | Verdict | Where it lives | Model |
|------------------|---------|----------------|-------|
| Fix 422 API errors | **Stale / wrong diagnosis** — verify once; real issue is timeouts + hydrate burst | Phase 0 smoke only | Composer |
| Frontend modernization (pump desk, responsive, viz) | **Important** — compact pump desk is P1 UI | Phase 2 + B0-d QA | Grok LOCK if mock unclear → Composer |
| SimiVision chat UX | **Important but separate** — `build_chat_context()` 25s timeout | Phase 4 (after stability) | Grok LOCK → Composer; Opus only if redesigning context architecture |
| Data pipeline (pump API, top-picks) | **Critical** — pump-alerts fast path unblocks desk | Phase 1; H1 hour-watch gated on B0-0 | Composer |
| Prediction/weights algorithms | **Defer** unless grading is wrong — J replay already landed | Existing learning slices | Grok medium if tuning; Composer to ship |
| Reliability & monitoring | **Important** — health gates, no timeout cache, unified Quiet | Phase 3 + Phase 0 | Composer |
| Judge panel merge resilience | **Light touch** — honest-empty already spec’d | B0-a / existing patterns | Composer |

---

## Model assignment (Opus is not “new features only”)

| Use **Composer 2.5** (default) | Use **Grok slow+medium** | Use **Opus 5** |
|--------------------------------|--------------------------|----------------|
| Locked plan execution (routes, tests, templates, cache fixes) | Ambiguous design; one-screen LOCK before build | Novel subsystem with **no repo pattern** (e.g. WebSocket hub, ingestion architecture) |
| Pump fast path, hydrate sequencing, compact UI from mock | Temporal/behavioral bugs (grading, replay, live streams) | **Cross-cutting architecture** when specs are weak and tradeoffs are large |
| Post-deploy curl gates, readiness hardening | Pre-merge review of large **behavioral** diffs | When Grok **medium FAILs** and the slice is still ambiguous |
| B0 empty-state taxonomy (VA-08) | Chat context scope LOCK (what to load, what to defer) | Full SimiVision **reasoning stack** redesign (not “fix timeout”) |

**Not Opus:** mechanical ports, template/CSS, “fix 422s”, cache policy, sequential hydrate — Grok+Composer are equal or better.

---

## Execution sequence

```text
Phase 0  Smoke + reconnect gate (B0-0 subset)     ← Ditto “reliability” + VA-00
  → Phase 1  Pump API fast path                   ← Ditto “data pipeline” (critical)
  → Phase 2  Compact pump desk UI                 ← Ditto “frontend modernization”
  → Phase 3  Hydrate stability + prod gates         ← Ditto “reliability & monitoring”
  → Phase 4  Chat context fast path (optional)    ← Ditto chat UX (after site stable)
```

**Hard gate:** Do not ship Phase 2 polish if Phase 1 still returns `status: "timeout"` on prod.

---

## Phase 0 — Reconnect smoke (1 PR, small)

**Branch:** `cursor/reconnect-smoke-d2cd`

**Intent:** Confirm Ditto’s 422 story is dead; establish baseline before stability slices.

**Work:**
1. Contract test + 5× prod curl: `/health`, `/api/subnets`, `/api/pump-alerts`, `/api/ops/readiness` — log status codes + latency
2. If any real 422: fix route collision (single-foundation rule); else document “timeouts not 422s” on board
3. Adopt **VA-02** subset: shared hydrate failure → Quiet card (no per-widget zombie) on Tier‑1 only

**AC:**
- [ ] No systemic 422 on CONTRACT routes
- [ ] Tier‑1 surfaces never eternal Loading after 5s (Quiet or real data)

**Model:** Composer

---

## Phase 1 — Pump API fast path (highest priority)

**Branch:** `cursor/pump-alerts-fast-d2cd`

**Intent:** Unblock pump desk data; stop caching failure.

**Work:**
1. `build_pump_alerts_desk()` — minimal fields, file-backed ladder only
2. `GET /api/pump-alerts` uses fast builder; no `kick_ladder` / whale warm on GET
3. Never cache timeout payloads; serve stale cache on timeout
4. Test: desk build <500ms locally

**AC:**
- [ ] 5× prod `/api/pump-alerts` <2s, `status != "timeout"`
- [ ] `alerts[]` populated when ladder file has entries

**Model:** Composer

---

## Phase 2 — Compact pump desk UI

**Branch:** `cursor/pump-desk-compact-d2cd`

**Intent:** Match reference “deck card” (Warming/Active + sparklines + formation %); less chrome on home spine.

**Work:**
1. `compact=true` on `pump_alert.html` for home spine
2. Hide eyebrow, sub, proof, detail card lane in compact mode
3. `cockpit_hydrate.js` `renderPumpAlerts()` for compact layout
4. 390px QA (G0 script + human spot-check)

**AC:**
- [ ] Visual match to agreed mock (image 2)
- [ ] Sparklines render when Phase 1 data present

**Model:** Grok medium LOCK if layout ambiguous → Composer

---

## Phase 3 — Hydrate stability + monitoring

**Branch:** `cursor/hydrate-stability-d2cd`

**Intent:** Stop white-screen flaps under hydrate burst; ops visibility.

**Work:**
1. Sequential tier‑1 hydrate: daily-pick → pump-alerts → then parallel rest
2. Cap hydrate concurrency in `cockpit_hydrate.js`
3. Worker: `ionice` / defer heavy pump scan (build on #458)
4. Longer pump cache TTL when data is fresh
5. Post-deploy gate: `scripts/verify_prod.sh` or CI — 10× `/health` 200 + parallel hydrate APIs don’t wedge
6. `/api/ops/readiness` returns useful degraded signal (not hang)

**AC:**
- [ ] `/health` <2s under hydrate storm
- [ ] `/` loads without 0-byte timeout on warm machine
- [ ] Readiness endpoint responds <3s

**Model:** Composer

---

## Phase 4 — Chat context (after stability)

**Branch:** `cursor/chat-context-fast-d2cd`

**Intent:** Fix “intelligence layer unreachable” / 25s busy — not a stability blocker for pump desk.

**Work:**
1. Grok LOCK: what context is essential vs deferrable for first token
2. Slim `build_chat_context()` — cache, parallel fetch, timeout per source
3. Client: clearer degraded message when partial context

**AC:**
- [ ] `POST /api/chat` or stream path responds <8s p95 with degraded partial context OK

**Model:** Grok LOCK → Composer; **Opus** only if redesigning multi-source context graph

---

## Explicitly out of this plan (Ditto list items)

| Item | Why defer |
|------|-----------|
| Full frontend modernization (all templates) | B0-a…d already sequenced; don’t boil ocean |
| New subnet metrics endpoints | Wave 4 YAGNI unless trader question is clear |
| Prediction/weights algorithm rewrite | No evidence grading is broken post-J |
| Alerting platform / PagerDuty | Env-gated O1 exists; add after hydrate stable |
| Draft #449 subnet connections | Separate slice; not prod blocker |

---

## Verify checklist (after each merge)

1. `pytest tests/test_endpoint_contract.py tests/test_prod_stability.py -q`
2. `./scripts/g0_phone_qa.sh` (or manual 390px)
3. 5× `curl -w '%{http_code} %{time_total}\n' https://<app>/api/pump-alerts`
4. `curl /health` + `GET /` size >0

---

## References

- `batch0-final-merged-plan.md` — B0-0 reconnect, VA-02/08
- `gameplan-pump-site-undeniable.md` — pump north star
- `model-guide.md` — Grok LOCK → Composer write
