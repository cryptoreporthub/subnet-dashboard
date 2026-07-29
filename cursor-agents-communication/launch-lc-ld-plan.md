# Launch plan — LC legal/trust/SEO + LD surface honesty

**Status:** ACTIVE  
**Created:** 2026-07-29  
**Baseline main:** `2ee0512` — LA #640 · LB #645 · violet accent #643 · audit honesty #631  
**Cadence:** One phase → one PR → merge → deploy → `./scripts/babysit_phase.sh <phase>` → human spot-check → next phase  
**Prereq:** LA + LB **DONE** on prod

---

## What we're fixing

| # | Problem | User impact |
|---|---------|-------------|
| **LC1** | No sitewide NFA disclaimer in footer/chrome | Legal/trust gap at launch |
| **LC2** | No `GET /robots.txt` | Crawlers get 404; SEO hygiene |
| **LC3** | `og:image` is `favicon.svg` — social crawlers want raster | Broken/weak link previews |
| **LC4** | Footer SSR still says generic "Live" vs LA hydrate honesty | Residual trust lie |
| **LC5** | Google Fonts loaded but CSP may not whitelist `fonts.gstatic.com` | Console CSP noise |
| **LD1** | `#habit-alert-btn` visible when `CONVICTION_ALERTS_ENABLED=off` | Dead button promises alerts |
| **LD2** | Chat shows generic errors; no honest "partial context" state | "Intelligence layer unreachable" confusion |
| **LD3** | Paper portfolio / watchlist hydrate failures show eternal loading | Zombie UI |
| **LD4** | SimiVision pick cards / hour cards may still show LONG without gate context | Honesty gap outside hero |
| **LD5** | Publish-gate copy inconsistent ("confidence" vs "audit gate") | Reader confusion |

**Out of scope:** Phase 4 accuracy lift (gated soak Aug 4), Chutes billing, payment/tier gates, new features.

---

## Execution order

```text
Phase LC  Legal / trust / SEO          ← merge → babysit lc → human footer/OG check
  → Phase LD  Surface honesty        ← merge → babysit ld → human 390px spot-check
```

**Hard gate:** Do not start **LD** until **LC** babysit green.

---

## Babysit contract

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh lc
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh ld
```

Minimum every phase: health 3/3 · `ops/live` worker alive · phase asserts below.

If babysit fails: **stop queue**, fix or rollback, re-babysit before next phase.

---

## Phase LC — Legal / trust / SEO

**Branch:** `cursor/launch-lc-trust-seo-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `server.py`, `templates/base.html`, `templates/partials/premium/footer.html`, `static/robots.txt` or route, `internal/security_headers.py`, tests

### Work

| ID | Change |
|----|--------|
| LC1 | Footer: add one-line NFA — *"SimiVision calls are scored council output, not financial advice. Do your own research."* on every page using `footer.html` |
| LC2 | `GET /robots.txt` — allow `/`, disallow `/api/`, `/metrics`, `/preview/`; link sitemap if exists else omit |
| LC3 | Add `static/og-share.png` (1200×630, existing brand colors) · point `og:image` + `twitter:card=summary_large_image` in `base.html` |
| LC4 | Footer SSR: align `footer_source_label` with LA logic — use `meta.stale` / `effective_source` when available from context; default honest "Snapshot" on degraded shell |
| LC5 | CSP: add `fonts.googleapis.com` + `fonts.gstatic.com` to `style-src` / `font-src` in `internal/security_headers.py` (prod already enforces CSP) |
| LC6 | Contract test: `GET /robots.txt` 200 · homepage contains NFA string · `og:image` ends with `.png` |

### Acceptance criteria

- [ ] View Source `/` — NFA line in footer
- [ ] `curl /robots.txt` — 200, sensible disallow rules
- [ ] Facebook/Twitter debugger (human): `og:image` resolves to PNG
- [ ] No new CSP console errors for fonts on home load
- [ ] `pytest tests/test_launch_lc_trust.py tests/test_endpoint_contract.py -q` green

### Babysit LC

- `GET /robots.txt` — 200
- `GET /` — grep NFA disclaimer + `og-share.png` in HTML
- Security headers present on `/`

**Human:** Open link preview (iMessage/Discord/Telegram) — card shows PNG, not broken image.

---

## Phase LD — Surface honesty

**Branch:** `cursor/launch-ld-surface-honesty-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `templates/partials/premium/council_stage.html`, `static/js/watchlist_alerts.js`, `static/js/paper_portfolio.js`, `static/js/chat_stream.js`, `static/js/cockpit_hydrate.js`, `templates/partials/premium/simivision_picks.html`, tests

### Work

| ID | Change |
|----|--------|
| LD1 | When `habit_alerts.enabled` is false: hide `#habit-alert-btn` + show one-line *"Conviction alerts off on this deploy"* in `#habit-alerts-summary` (SSR + JS) |
| LD2 | Chat: on timeout/partial context, show *"Partial context — council data loaded, live feeds still warming"* instead of generic error; keep send disabled until ready |
| LD3 | Paper portfolio: on API fail/empty, replace loading with Quiet card (match VA-02 pattern); never eternal spinner |
| LD4 | Watchlist: empty state *"No pinned subnets"* vs error *"Watchlist unavailable"*; pin button stays usable |
| LD5 | SimiVision + hour pick cards: reuse degraded/HOLD styling from #631 when `action==HOLD` or `scenario_tags.fallback`; headline uses `action` not `pick` presence |
| LD6 | Publish-gate copy: one canonical string from `publish_gate_label()` in hold_reason templates + pick cards |
| LD7 | Tests: `test_launch_ld_surface.py` — alerts hidden when env off; pick card HOLD markup; paper portfolio quiet on empty |

### Acceptance criteria

- [ ] Prod with `CONVICTION_ALERTS_ENABLED=off`: no clickable alert CTA on home
- [ ] Throttle network → paper portfolio shows Quiet, not spinner forever
- [ ] SimiVision HOLD pick shows degraded note (not LONG badge)
- [ ] Chat degraded message is specific, not "unreachable"
- [ ] `pytest tests/test_launch_ld_surface.py tests/test_endpoint_contract.py -q` green

### Babysit LD

- `GET /` — no `habit-alert-btn` when alerts disabled (or `data-enabled="0"` + hidden)
- `GET /api/portfolio/status` — 200
- `GET /api/daily-pick` — HOLD/long consistent with card markup grep

**Human:** 390px — pin/watchlist, paper portfolio, chat degraded path; no dead buttons.

---

## PR checklist (every phase)

1. Branch `cursor/<slug>-7728` off latest `main`
2. Targeted `pytest` + contract
3. Push → PR → CI green → merge
4. Wait deploy (~3–5 min)
5. `./scripts/babysit_phase.sh <phase>`
6. Human spot-check per phase AC
7. Ditto STATUS + `board.md` row

---

## After LC + LD

| Track | Next |
|-------|------|
| **Human H1** | 390px SS-TG sign-off |
| **Human H2** | Soak day 7 — Aug 4 |
| **Agent** | Finish-queue Slice 4 when `graded > 0` |
| **Gated** | Phase 4 accuracy lift post-soak GO |

---

## References

- LA/LB plan (merged): hero truth + integrations rail
- `post-audit-sprint-plan.md` Phase D (CSP — mostly done, fonts gap remains)
- `s23-share-png-plan.md` (OG PNG)
- `finish-queue-plan.md` Slice 5 (390px fixes — only if H1 fails)
- `DEPLOY.md` — `CONVICTION_ALERTS_ENABLED` env gate
