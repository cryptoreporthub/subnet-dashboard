# Post-hero / mindmap finish plan — merge → review → next

**Created:** 2026-08-02  
**main at plan:** `c8901a0` (#738 magenta sweep)  
**Just shipped:** #736 hero ACs · #738 violet tokens · #734 timeouts · #729/#731 mindmap 2a/2b · #719–#721 loops  
**Cadence (mandatory):** one PR → merge → babysit → human glance → next PR. No stacking.

---

## Cadence (every step)

```bash
# After merge + Fly deploy (~5–10 min)
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint
BASE=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh   # when UI touched
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
```

| Gate | Pass means |
|------|------------|
| CI smoke | green on the PR |
| Fly `/health` | 200 |
| Hero cold load | `#k3-dossier` present; horizon badge visible; orb not fake-0% when missing |
| Trust | accuracy still gated on `trust_banner.ready` |
| Mindmap | `/api/mindmap/graph` + `/trail` + `/summary` non-5xx |

**Human review between steps:** 390px glance (LONG or honest HOLD + why) OR ops checklist for backend-only PRs. Do not start step N+1 until step N is on `main` and babysit is clean (or WARN-only known soak noise).

---

## Already done (do not re-open)

| Item | PR |
|------|-----|
| Hero missing≠zero + horizon badge + sample-size copy | #736 (+ prior H1/H2) |
| Mindmap loop integration + visual spine | #729 · #731 |
| Judges / MI author-trust loops | #720 · #721 |
| soul_map I/O + read cache | #718 · #719 |
| API timeout wrappers (subnets/judges/learning-health) | #734 |
| Hot-pink → violet token sweep in `premium.css` | #738 |
| Mindmap `integration_status` honesty (M1–M5) | #725–#735 |

---

## Queue (execute in order)

Branch prefix: `cursor/<slug>-1d2f`

### Step 0 — Deploy babysit (no PR)

**Why:** #736+#738 just landed; readiness showed `readiness_build_timeout` / `busy` at merge time.

- [x] Wait for Fly Deploy on `main@c8901a0` (or newer) to finish
- [x] Run babysit + `g0_phone_qa` + learning-loop check (#744–#749 era)
- [x] Confirm hero SSR: `#k3-dossier` / hydrate PASS via g0 pack
- [ ] **Human:** 390px cold load — HOLD/LONG glance test (AC7)
- [x] Log result in Ditto STATUS (`main=<sha>`)

**Stop if:** `/health` 5xx, home white-screen, orb shows `0` when confidence missing.

---

### Step 1 — Brand gradient token consolidation (MECHANICAL)

**Branch:** `cursor/premium-gradient-tokens-1d2f`  
**Scope:** Claude Medium — collapse ad-hoc gradients in `premium.css` onto `--board-border-gradient` / `--important-border-gradient` (and existing accent tokens). No new palette.

| Touch | Do |
|-------|-----|
| `static/css/premium.css` | `.section-title::before`, `.card::after`, leftover rail gradients → tokens |
| `tests/test_premium_accent_tokens.py` | Assert no third/fourth one-off brand gradients (extend guard) |

**Out:** retheme, council_stage inline K3 CSS rewrite, pd/pds.

**Review:** desktop + 390 screenshot of section titles / pick cards.  
**Merge → babysit → next.**

---

### Step 2 — Dead badge/tag CSS cleanup (MECHANICAL)

**Branch:** `cursor/premium-badge-tag-dedupe-1d2f`  
**Scope:** Claude Low — collapse duplicate `.badge-*` / `.tag-*` `!important` stacks in `premium.css` to one rule per semantic tag.

**Out:** JS class renames sitewide (keep both selectors pointing at one declaration if needed).

**Review:** HOLD/LONG/WATCH chips still colored.  
**Merge → babysit → next.**

*(May combine with Step 1 if diff stays &lt; ~80 lines — only if babysit after Step 0 is green.)*

---

### Step 3 — MindmapBridge recommendations honesty (MECHANICAL)

**Branch:** `cursor/mindmap-bridge-recs-honesty-1d2f`  
**Scope:** pack2 gap — `get_brain_recommendations()` is still a registry heuristic, not live council.

| Touch | Do |
|-------|-----|
| `internal/council/mindmap_bridge.py` | Label payload: `source: "registry_heuristic"`; keep honest-empty when empty |
| Call sites (`server.py` enrich / API) | Surface `source` + `data_available` so UI never presents heuristic as council |
| Tests | Extend `test_phase_g_mindmap_graph.py` / small unit — no SN1/2/3 theater |

**Out:** replacing selector scoring with live council (bigger slice; defer unless LOCK).

**Review:** API JSON shows heuristic vs empty clearly.  
**Merge → babysit → next.**

---

### Step 4 — LB-11 trail fetch owner (MECHANICAL)

**Branch:** `cursor/lb11-trail-fetch-owner-1d2f`  
**Scope:** verify #729 fixed dual-fetch; if Living Focus still races, make hydrate the sole owner + `home:hydrate-trail` only.

| Touch | Prefer |
|-------|--------|
| `static/js/cockpit_hydrate.js` | Keep single trail fetch |
| `static/js/living_focus.js` | Never fetch if cache/event pending; no second `?limit=40` race |

**Out:** trail schema changes.

**Review:** Network tab — one `/api/mindmap/trail` on cold home.  
**Merge → babysit → next.**

---

### Step 5 — Hero + mindmap 390px sign-off pack (docs + light fix)

**Branch:** `cursor/hero-mindmap-390-signoff-1d2f`  
**Scope:** agent runs `g0_phone_qa` + notes; only ship fixes for failures found (no drive-by redesign).

- [ ] Record checklist in PR body (hero ACs 1–7, mindmap graph/trail visible, focus strip)
- [ ] Human signs H1-style 390px in PR comment or Ditto
- [ ] Patch only regressions found

**Merge → babysit → next.**

---

### Step 6 — Board STATUS sync (docs-only)

**Branch:** `cursor/board-status-aug2-1d2f`  
**Scope:** refresh `cursor-agents-communication/board.md` STATUS SNAPSHOT to current `main` (hero/mindmap/timeouts/magenta done; #719–#721 merged). Cite this plan for the remaining queue.

**Out:** rewriting roadmap phases unrelated to this finish queue.

**Merge → Ditto STATUS post → next.**

---

### Step 7 — Soak / Acc (GATED — human calendar)

| Gate | When | Action |
|------|------|--------|
| H2 Track 1 soak | **2026-08-04** | `soak_review_snapshot.sh` → GO/NO-GO |
| H3 soak | **2026-08-11** | same |
| Accuracy lift / Slice 7 | **only after H2 GO** | follow `accuracy-pump-pattern-plan.md` / completion-runbook Wave 3 |

Do **not** start Acc experiment PRs before H2 GO.

---

## Explicit defer (ticket, do not start in this queue)

| Item | Why defer |
|------|-----------|
| pd-/pds- hero card duplication extract | Real debt; needs DESIGN-HEAVY LOCK + shared helper; wrong after token polish |
| Full HTML-string → template migration in `cockpit_hydrate.js` | Multi-PR redesign; not a finish-queue slice |
| Blind-merge #692 / #675 / #374 | Ground-up mandate; ideas only |
| split_v2 re-enable | Canon = v1 inline; needs probe soak + human |
| Chutes / live LLM chat | Out of product slice |

---

## Model rules

| Step type | Gate |
|-----------|------|
| 1–4, 6 MECHANICAL | Composer implements; optional Sonnet on **diff** if stuck |
| 5 sign-off | Agent babysit + **human** glance |
| 7 soak / Acc | Human GO first; then Grok LOCK → Composer |
| pd/pds or hydrate templating | DESIGN-HEAVY — Grok LOCK + **one** Sonnet on LOCK before Composer |

---

## Definition of done (this plan)

- [ ] Steps 0–6 on `main` with babysit green (or documented WARN)
- [ ] Human 390px hero glance recorded
- [ ] Deferrals listed above remain tickets, not silent drops
- [ ] Step 7 only after H2 soak GO
- [ ] Ditto STATUS: `main=<sha>`, queue position, open PRs

---

## Start prompt (Composer)

```
Execute Step <N> from cursor-agents-communication/post-hero-finish-plan.md only.
Branch cursor/<slug>-1d2f from latest main. One PR. Ponytail minimal diff.
After CI green: human merges (or agent merges if allowed), then babysit before Step N+1.
Do not start deferred items. Do not edit board.md except on Step 6.
```
