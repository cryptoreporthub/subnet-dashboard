# Automated Build Plan — Phase B finish → hydration → experience

**Created:** 2026-07-14 by Agent (`-6f98`)  
**For:** Human hits **Build** once per slice (or batch if agent auto-continues)  
**`main` baseline:** `b3bf9d2` (B1–B5 merged)

---

## Automated decision (no human pick needed)

| Priority | Slice | Why this order |
|----------|-------|----------------|
| **1 — BUILD NOW** | **B6** slowapi | Last Phase B audit item (#9); hardens single Fly worker before more UI load |
| **2** | **C4** hydration binders | Phase 4 gate per `cursor-implementation-guide.md`; unblocks C5/C6 |
| **3** | **C5** APY/confidence hydration | Fixes double-multiply (pairs with B5 data truth) |
| **4** | **C6** conviction tiers | Align Jinja ↔ JS after C5 |
| **5** | **C1** uPlot migration | Phase C experience; needs honest data layer (B1–B5 done) |
| **6** | **C2** datastar SSE hydration | Live 12-panel updates without SPA |
| **7** | **C3** CSS/mobile/a11y | Polish pass last |

**Deferred (human-only, not agent):** A2 branch-protection toggle in GitHub Settings.

---

## Automation contract (every slice)

Applies to all slices below unless noted.

1. **Branch:** `cursor/<slice-slug>-6f98` off latest `main`
2. **Grok:** `grok-4.5-high-fast` design/review for backend slices (B6); full xhigh only on CONDITIONAL/FAIL
3. **Build:** Composer implements from this plan (minimal Ponytail diff)
4. **Test:** `source .venv/bin/activate && PYTHONPATH=/workspace pytest tests/test_endpoint_contract.py` + slice tests
5. **PR:** push → open PR → mark ready → **auto-merge when CI green** (standing user instruction)
6. **Board:** update `cursor-agents-communication/board.md` + `docs/IMPLEMENTATION_PLAN.md` status line
7. **Do not** use GitHub Contents API; git only
8. **Do not** edit this plan file during Build turns

---

## Slice 1 — B6: slowapi rate limiting (audit #9) ← **HIT BUILD HERE**

### Goal
Protect the single Fly.io uvicorn worker from abuse; return `429` with standard slowapi handler.

### Design (locked — Grok-fast pattern)

| Item | Choice |
|------|--------|
| Library | `slowapi==0.1.9` (pins `limits`) |
| Key | `get_remote_address` (Fly passes client IP via `Fly-Client-IP` / `X-Forwarded-For` — use slowapi default; document env override if needed) |
| Default limit | `RATE_LIMIT_DEFAULT=120/minute` (env override) |
| Disable switch | `ENABLE_RATE_LIMIT=0` → no limiter mount (CI/tests friendly) |
| Exempt paths | `/health`, `/api/health`, `/metrics`, `/static/*` |
| Stricter routes | `POST /api/simivision/chat`, `POST /api/mindmap/feedback` → `30/minute` per IP |

### Files to touch

| File | Change |
|------|--------|
| `requirements.txt` | `slowapi==0.1.9` |
| `server.py` | Limiter on `app.state`; `RateLimitExceeded` handler; mount after metrics block, before routers; apply default limit via middleware or decorator on hot routes |
| `internal/rate_limit.py` | **New** — `get_limiter()`, `limit_or_noop` helper, exempt path check |
| `tests/test_rate_limit.py` | **New** — smoke: under limit 200; exempt `/health` never 429; over-limit returns 429 (monkeypatch low limit) |

### Out of scope
- Per-user API keys, Redis backend, Fly edge rate limits
- slowapi on background schedulers

### Commits
1. `B6: add slowapi rate limiter with env gate (audit #9)`
2. `test: rate limit smoke + exempt paths`

### PR title
`B6: slowapi rate limiting (audit #9)`

---

## Slice 2 — C4: hydration binders (`base.html` + chart paint)

### Goal
Wire `cockpit_hydrate.js` (and chart paint hooks) in `base.html` so premium panels hydrate on load.

### Files
- `templates/base.html` — script tags, defer order
- `static/js/cockpit_hydrate.js` — ensure DOM-ready binders only (no APY math yet)
- `tests/test_phase_h_ui.py` — assert hydrate script present on `/`

### Grok
Light review only (Composer build) — visual/structural, not behavioral risk.

### PR title
`C4: cockpit hydration binders in base.html`

---

## Slice 3 — C5: APY/confidence double-multiply fix

### Goal
Hydration JS must use `subnet_apy_percent` semantics (B5): no `* 100` on already-percent values.

### Files
- `static/js/cockpit_hydrate.js` — APY/confidence scaling
- `static/js/premium_scanner.js` — same rule as hydrate (≤1 → ×100, else as-is)
- `tests/test_cockpit_data_fixes.py` — hydration parity cases if testable via exported helper

### PR title
`C5: fix APY/confidence double-multiply in hydration`

---

## Slice 4 — C6: conviction tier alignment

### Goal
Jinja conviction badges and JS tiers use identical thresholds.

### Files
- `templates/partials/premium/*.html` — tier cutoffs
- `static/js/cockpit_hydrate.js` — matching constants (single source: inline config or shared `static/js/conviction_tiers.js`)
- `tests/test_phase_h_ui.py` — tier label assertions

### PR title
`C6: align conviction tiers Jinja ↔ JS`

---

## Slice 5 — C1: uPlot migration (audit #10 partial)

### Goal
Replace Chart.js on premium cockpit time-series canvases with uPlot (~40KB).

### Files
- `static/js/` — new `uplot_charts.js`; remove Chart.js from premium partials
- `templates/partials/premium/` — canvas targets from Phase 2 G1 wrappers
- `tests/test_phase_h_ui.py` — no Chart.js script tag on `/`

### Grok
**grok-4.5-high-fast** design spike before build (chart mapping table: which panel → which series).

### PR title
`C1: uPlot migration for premium cockpit charts`

---

## Slice 6 — C2: datastar SSE live hydration (audit #10 partial)

### Goal
SSE endpoint pushes section JSON; datastar patches DOM for 12 panels (no SPA).

### Files
- `server.py` — `GET /api/cockpit/stream` or similar SSE route
- `internal/cockpit/` — serial section emitter
- `templates/base.html` — datastar script + `data-on-signal`
- `tests/test_endpoint_contract.py` — add SSE route if HTTP 200/EventStream

### Grok
**grok-4.5-high-fast** architecture pass (event shape, reconnect, honest-empty).

### PR title
`C2: datastar SSE cockpit hydration`

---

## Slice 7 — C3: CSS / mobile / a11y pass

### Goal
WCAG contrast, touch targets, responsive premium cockpit polish.

### Files
- `static/css/premium.css`, `responsive.css`
- `templates/partials/premium/header.html` — freshness badge a11y (`aria-live`)

### Grok
Pre-merge sign-off (fast-xhigh) on visual diff.

### PR title
`C3: premium cockpit CSS/mobile/a11y pass`

---

## Status snapshot (pre-build)

| Item | State |
|------|-------|
| Phase A | ✅ complete |
| B1–B5 | ✅ merged (#174–#182) |
| B6 | ⏳ **next build** |
| Phase 4 C4–C6 | backlog |
| Phase C C1–C3 | backlog |
| A2 branch protection | manual |

---

## Build instruction

**Slice 1 (B6)** is the only scope for the next Build click. After B6 merges, agent continues Slice 2 automatically unless gated.

Do not regress B1 guardrails (`AUTO_SYNC` off in CI, chain timeout) or B3 scheduler shutdown gate.
