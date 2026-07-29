# Launch plan — Hero source-of-truth + Connected integrations rail

**Status:** ACTIVE  
**Created:** 2026-07-29  
**Baseline main:** `a4e4624` — audit honesty #631 merged · finish-queue Slices 0–3 · cache fix #629  
**Cadence:** One phase → one PR → merge → deploy (~3–5 min) → `./scripts/babysit_phase.sh <phase>` → human spot-check → next phase  
**Depends on:** `post-audit-sprint-plan.md` Phase C (worker split) **DONE** · audit honesty #631 **DONE**

---

## What we're fixing

| # | Problem | User impact |
|---|---------|-------------|
| **A** | Hero shows **LONG** in headline/badge while body or footer says **HOLD** (or vice versa) after hydrate/SSE | Trust collapse on the one job the site sells |
| **A** | `/api/daily-pick` served from **web** process while pick file lives on **worker volume** | SSR and hydrate read different picks |
| **A** | Timeout/pending hydrate **overwrites** good SSR with empty or contradictory state | Flash of wrong call |
| **A** | Footer/header says **Live** when meta is snapshot/stale/fallback | Legal/trust lie |
| **B** | Integrations strip is `hidden` until JS fetch succeeds; vanishes on error | "Built on Bittensor" invisible at launch |
| **B** | Market Pulse uses a full 4-cell grid; integrations demoted below fold | Connected subnets (incl. Chutes) not visible above fold |
| **B** | Chutes connected in prod but UI may show offline (probe/base URL) | Green dot missing despite live key |

**Out of scope here:** Phase 4 accuracy lift (gated soak), SS-TG 390px human gate, new integrations beyond the existing six primary rows.

---

## Execution order

```text
Phase LA  Hero source-of-truth          ← merge → babysit → human hero check
  → Phase LB  Integrations + pulse rail  ← merge → babysit → human strip check
```

**Hard gate:** Do not start **LB** until **LA** babysit green and hero shows one consistent action (LONG or HOLD) through a full page load + 60s SSE refresh.

---

## Babysit contract

After each merge + Fly deploy:

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh la   # Phase LA
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh lb   # Phase LB
```

Minimum manual checks (both phases):

1. `GET /health` — 200 in <2s (3 probes)
2. `GET /api/ops/live` — `worker_peer.alive: true`
3. `GET /` — 200, cockpit shell loads, no eternal spinner on hero
4. Phase-specific asserts below

If babysit fails: **stop queue**, fix or rollback, re-babysit before next phase.

---

## Phase LA — Hero source-of-truth

**Branch:** `cursor/hero-source-truth-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `internal/worker_proxy.py`, `server.py`, `static/js/cockpit_hydrate.js`, `static/js/home_live_refresh.js`, `templates/partials/premium/council_stage.html`, `static/js/data_freshness.js`, tests

### Root causes (confirmed in repo)

1. `should_proxy_path()` proxies pump-alerts + message-intel but **not** `/api/daily-pick` — web and worker can disagree.
2. `renderDailyPick` / `patchK3DossierFromPayload` always apply hydrate payload; a `pending`/timeout response can flip badge/headline away from SSR truth.
3. `home_live_refresh.js` SSE path can patch hero on 60s tick without comparing `generated_at` / `action` monotonicity.
4. `renderFooterStatus` → `friendlySourceLabel` collapses timeout/fallback to generic "Snapshot" without `meta.stale` / `effective_source`.
5. SSR `council_stage.html` uses `act` for headline but `audit_pick` presence can imply LONG in copy while `action` is HOLD.

### Work

| ID | Change |
|----|--------|
| LA1 | Add `/api/daily-pick` (+ `/api/daily-pick/weighed` if volume-backed) to `should_proxy_path()` when `needs_worker_volume_proxy()` |
| LA2 | `GET /api/daily-pick`: include `generated_at`, `data_source` (`volume` \| `local` \| `pending`), `stale: bool` in JSON meta |
| LA3 | **Monotonic hydrate:** `patchK3DossierFromPayload` / `renderDailyPick` — reject downgrades when incoming payload lacks `pick`+`action` or has older `generated_at` than SSR `data-generated-at` attribute |
| LA4 | **Pending guard:** if `status === 'pending'` or empty body, no-op hero patch (keep SSR); show subtle "updating…" on `#k3-dossier` only |
| LA5 | **Single action source:** headline, `#k3-action-badge`, and glow tier all derive from `payload.action` (not `pick` presence alone); HOLD + candidate shows "HOLD · {name}" consistently |
| LA6 | **Footer/header honesty:** wire `patchDataFreshnessFromSubnetMeta` + daily-pick meta → badge text `LIVE` / `STALE` / `SNAPSHOT` / `CACHE` with `meta.stale` and `effective_source` |
| LA7 | **Fallback label:** when `hold_reason` or `scenario_tags.fallback`, add `k3-claim--degraded` + one-line note (mirror pick-card degraded pattern from #631) |
| LA8 | `home_live_refresh.js`: same monotonic rules as LA3–LA4 before calling `renderDailyPick` |
| LA9 | Tests: `test_worker_volume_proxy.py` daily-pick proxy; `test_hero_hydrate_monotonic.py` (new) — pending must not flip LONG→HOLD; `test_endpoint_contract.py` unchanged routes |

### Acceptance criteria

- [ ] 5× prod `curl /api/daily-pick` <8s, same `action` as SSR hero on cold load
- [ ] Simulated slow `/api/daily-pick` (dev): SSR HOLD/LONG unchanged after 35s timeout
- [ ] Footer badge matches `/api/data-freshness` `effective_source` (not hardcoded "Live")
- [ ] No headline/badge mismatch in static HTML + post-hydrate DOM
- [ ] `pytest tests/test_worker_volume_proxy.py tests/test_hero_hydrate_monotonic.py tests/test_endpoint_contract.py -q` green

### Babysit LA

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh la
```

Script checks (add to `babysit_phase.sh`):

- 3× `GET /api/daily-pick` — 200, `action` in (`long`, `HOLD`), `generated_at` present
- `GET /` — grep `#k3-action-badge` text matches `k3-call-headline` LONG/HOLD token
- `GET /api/data-freshness` — `effective_source` not empty

**Human:** hard refresh `/`, wait 90s (SSE tick), confirm hero action unchanged; throttle network → hero stays on SSR.

---

## Phase LB — Connected integrations + compact Market Pulse

**Branch:** `cursor/integrations-pulse-rail-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `templates/partials/premium/pulse_strip.html`, `templates/partials/premium_cockpit.html`, `static/js/subnet_integrations.js`, `static/css/situation_room.css`, `static/css/premium.css`, `server.py` (SSR context), `internal/integrations/status.py` (Chutes probe only if needed), tests

### Design (agreed)

- **One ribbon** below hero: top row = compact Market Pulse (one line); bottom row = integrations strip.
- Pulse shrinks to: `Breadth · Avg 24h · N signals` (drop Risk watch cell to sub-line or omit on mobile).
- Integrations: `● Finney ● Blockmachine ● DeSearch ● Chutes ● Thirty Spokes ● Ditto` + `6/6 live`.
- **SSR skeleton** renders immediately (gray dots); JS upgrades to live colors.
- **Never hide** on fetch failure — show last SSR + "checking…" or stale count.

### Work

| ID | Change |
|----|--------|
| LB1 | Merge pulse + integrations into `pulse_strip.html` — single `#section-market-pulse` container with `.sr-pulse__oneline` + `#subnetIntegrationsBar` inline (remove separate hidden bar in cockpit) |
| LB2 | SSR: `server.py` `_fast_home_hero_context` or index builder calls `build_integrations_status()` (cached 60s) → template renders skeleton strip server-side |
| LB3 | `subnet_integrations.js`: on fetch fail, **keep** SSR strip visible; add `.subnet-int-strip--stale` class; poll retry unchanged |
| LB4 | Compact CSS: single-line pulse grid (`grid-template-columns: auto 1fr auto`); integrations row flex-wrap @390px |
| LB5 | Verify Chutes probe: `CHUTES_API_KEY` + `https://llm.chutes.ai/v1/models` → `connected`; add regression test if probe regresses |
| LB6 | Footer `integrations` count syncs from same payload |
| LB7 | Tests: `test_subnet_integrations.py` SSR context optional; new `test_integrations_strip_ssr.py` — GET `/` contains `subnet-int-strip` without JS |

### Acceptance criteria

- [ ] Above-fold ribbon visible on first paint (View Source shows integration skeleton)
- [ ] Chutes dot **green** on prod (user confirmed key live)
- [ ] Fetch failure (block `/api/subnet-integrations` in devtools): strip stays, shows stale/skeleton — not `hidden`
- [ ] Market pulse readable at 390px in one row
- [ ] `pytest tests/test_subnet_integrations.py tests/test_integrations_strip_ssr.py tests/test_endpoint_contract.py -q` green

### Babysit LB

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh lb
```

Script checks:

- `GET /api/subnet-integrations` — 200, `connected_count >= 4`, chutes `status === 'connected'`
- `GET /` — HTML contains `subnet-int-strip` and `Built on Bittensor`
- `GET /` — `#section-market-pulse` present, not `hidden`

**Human:** 390px screenshot — pulse one-liner + all six integrations visible without scroll.

---

## PR checklist (every phase)

1. Branch `cursor/<slug>-7728` off latest `main`
2. `pytest` targeted + contract
3. Push → PR (draft OK) → CI green
4. Merge → wait deploy
5. `./scripts/babysit_phase.sh <phase>`
6. Human spot-check per phase
7. Ditto `save_memory` STATUS + `board.md` row

---

## Board sync (after both phases)

Add to `board.md` under **Launch readiness**:

| Phase | Status |
|-------|--------|
| LA Hero truth | pending |
| LB Integrations rail | pending |

---

## References

- Audit honesty merged: #631 (`hourly HOLD`, trends, degraded cards)
- Worker proxy: `internal/worker_proxy.py`, #603 live-cache proxy
- Integrations API: `docs/SUBNET_INTEGRATIONS.md`, `internal/integrations/status.py`
- Hydrate sequencing: `static/js/cockpit_hydrate.js` tier 1a daily-pick first
- Finish queue: `finish-queue-plan.md` (Slice 2 freshness badge overlaps LA6 — coordinate, don't duplicate)
