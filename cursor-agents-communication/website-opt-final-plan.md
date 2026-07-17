# §31 — Website optimization FINAL plan (22 ideas)

**Status:** ACTIVE · full queue (no optional skips)  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `61bb3e7`  
**Source:** Agent deep-dive (10) + Grok slow+low review (10) → merged  
**Supersedes:** `website-opt-20-plan.md` (same IDs; optionals now in queue)

## Agent prompt

```
§31 WEBSITE OPT — FINAL:
- Read board.md → this file → active slice AC only.
- Branch: cursor/opt-<slug>-c3fd off latest main.
- One slice per PR · merge when CI green · auto-continue.
- No data/*.json · RF-2 · no custom domain (H1).
- Grok slow+low only on AC fail / DESIGN ambiguity.
```

## Out of scope

| Item | Reason |
|------|--------|
| H1 custom domain / CDN | User skipped |
| H2–H6 | Human infra (Telegram, Discord, email, listener creds, Fly volume) |
| D1–D7 | Redis, Bittensor SDK, EMA nudge, sell-alert push, owner overlay, extrinsic links, full money-flow graph |

---

## Idea registry (O1–O22)

| ID | Title | Tier | Imp | Eff |
|----|-------|------|-----|-----|
| O1 | Homepage fetch storm + Focus daily-pick dedupe | 1 | H | M |
| O2 | Kill SSE-tick + 60s dual refresh | 1 | H | M |
| O3 | Slim `/api/subnets` client fields | 1 | H | M |
| O4 | Unblock Google Fonts `@import` | 1 | M | S |
| O5 | Wallet share single `investigate_wallet` | 1 | H | S |
| O6 | Search + predictions memo | 2 | H | S |
| O7 | `Cache-Control` map for heavy GETs | 2 | H | S |
| O8 | Prod SN name integrity hard-fail | 2 | H | M |
| O9 | `verify_prod` name + SSE + hydrate probes | 2 | M | S |
| O10 | Share OG / Twitter image meta | 2 | M | S |
| O11 | Mobile Living Focus layout | 3 | M | S |
| O12 | Investigation seller→owner batch | 3 | M | M |
| O13 | Story strip / path / Focus overlap | 3 | M | S |
| O14 | Muted text contrast WCAG | 3 | M | S |
| O15 | Command palette a11y | 3 | M | S |
| O16 | Static asset fingerprint / longer TTL | 4 | M | M |
| O17 | Bundle core home JS + lazy drawer modules | 4 | M | M |
| O18 | `get_merged_subnet` O(1) index | 4 | M | S |
| O19 | SQLite connection reuse in fetchers | 4 | M | M |
| O20 | Learning snapshot module cache | 2 | M | S |
| O21 | Share-page empty/error states | 4 | L | S |
| O22 | CSS scroll-row dedupe | 4 | L | S |

---

## Automated queue (sequential · all slices required)

| # | Slice | IDs | Branch slug | State |
|---|-------|-----|-------------|-------|
| **§31-0** | Final plan + board sync | — | `opt-final-plan-c3fd` | ✅ this PR |
| **§31-1** | Homepage data bus | O1, O2 | `opt-home-data-bus-c3fd` | next |
| **§31-2** | Wallet + fonts | O5, O4 | `opt-wallet-fonts-c3fd` | pending |
| **§31-3** | Cache + search/learning memo | O7, O6, O20 | `opt-cache-memo-c3fd` | pending |
| **§31-4** | Slim subnets + names + verify | O3, O8, O9 | `opt-slim-names-c3fd` | pending |
| **§31-5** | Share OG + mobile + contrast | O10, O11, O14 | `opt-share-mobile-c3fd` | pending |
| **§31-6** | Inv + narrative + palette a11y | O12, O13, O15 | `opt-inv-a11y-c3fd` | pending |
| **§31-7** | Static TTL + JS bundle + merged index | O16, O17, O18 | `opt-static-bundle-c3fd` | pending |
| **§31-8** | SQLite reuse + empty states + CSS | O19, O21, O22 | `opt-fetcher-polish-c3fd` | pending |

**After §31-8:** website optimization complete. Board → idle unless user opens new phase.

---

## Slice acceptance criteria

### §31-1 — Homepage data bus (O1, O2)
- [ ] `window.HomeHydrateCache` (or `HomeData`) is the single writer from `cockpit_hydrate.js`
- [ ] `living_focus.js` waits ≤2s for `home:hydrate-cache` before cold fetch
- [ ] `refreshFocus()` does not re-fetch `/api/daily-pick` when cache fresh
- [ ] `home_live_refresh.js` does not duplicate full `/api/subnets` on SSE tick + 60s interval for same payload
- [ ] Contract tests green

**Files:** `static/js/cockpit_hydrate.js`, `living_focus.js`, `home_live_refresh.js`

### §31-2 — Wallet + fonts (O5, O4)
- [ ] `wallet_share_page`: one `investigate_wallet` call, reused for activity + flows
- [ ] No `@import` Google Fonts in `base.css`
- [ ] Home + share pages load fonts via preconnect/async or self-host with honest fallback

**Files:** `internal/share_pages/routes.py`, `static/css/base.css`, share/home templates

### §31-3 — Cache + memo (O7, O6, O20)
- [ ] `server.py`: path→TTL dict for subnets/council/judges/search/learning-metrics
- [ ] `global_search`: skip predictions scan when `len(q) < 8`; 60s in-mem memo
- [ ] `_learning_snapshot()` ≤30s shared by stats/metrics/mindmap routes

**Files:** `server.py`, `internal/share_pages/search.py`, `internal/learning/routes.py`

### §31-4 — Slim subnets + names + verify (O3, O8, O9)
- [ ] Home hydrate uses `GET /api/subnets?limit=&fields=` (or dedicated slim endpoint)
- [ ] No API/UI emits `SNNone` or null display names
- [ ] `verify_prod.sh`: no `SNNone`, SSE `once=1` 200, sample subnet name check

**Files:** `server.py`, `internal/subnet_names.py`, `scripts/verify_prod.sh`, hydrate JS

### §31-5 — Share OG + mobile + contrast (O10, O11, O14)
- [ ] Share pages: `og:image`, `og:title`, `twitter:card=summary_large_image`
- [ ] Living Focus readable at ≤640px (judge grid, chips, learn strip)
- [ ] `--stage-muted` and share muted text ≥4.5:1 contrast

**Files:** `templates/share/base_share.html`, share routes, `council_first.css`, `share_pages.css`

### §31-6 — Inv + narrative + palette a11y (O12, O13, O15)
- [ ] Owner-check: single batched API round-trip (or server-side batch endpoint)
- [ ] Above-fold: one primary narrative (Living Focus); story path / strip deferred in drawer or collapsed
- [ ] Command palette: listbox + `aria-expanded` + `aria-activedescendant`

**Files:** `investigation_panel.js`, `premium_cockpit.html`, `command_palette.js`

### §31-7 — Static TTL + JS bundle + merged index (O16, O17, O18)
- [ ] Static assets: `Cache-Control: immutable` or content-hash filenames for JS/CSS
- [ ] Home loads ≤3 script tags for core path; drawer modules load on `<details>` open
- [ ] `get_merged_subnet(netuid)` is O(1) dict lookup, invalidated with SQLite TTL

**Files:** `server.py`, `templates/partials/premium/scripts.html`, `fetchers/merged_data.py`, optional `scripts/bundle-home.sh`

### §31-8 — SQLite reuse + empty states + CSS (O19, O21, O22)
- [ ] Fetcher cache modules use one WAL SQLite connection + lock (no connect-per-read)
- [ ] Share wallet/subnet pages: honest empty + retry when TaoStats/investigate dark
- [ ] Shared `.simi-scroll-row` / `.simi-scroll-card` replaces duplicate story/portfolio/letter CSS

**Files:** `fetchers/*.py`, share templates/CSS, `council_first.css`

---

## Grok review notes (archived)

| Original | Verdict |
|----------|---------|
| A1 fetch storm | KEEP / UPGRADE |
| A2 wallet double-fetch | KEEP |
| A3 search memo | KEEP |
| A4 Cache-Control | KEEP |
| A5 learning I/O | MERGE → O6/O20 |
| A6 JS bundle | DOWNRANK → §31-7 O17 |
| A7 fonts | KEEP |
| A8 palette a11y | DOWNRANK → §31-6 O15 |
| A9 merged O(n) | DOWNRANK → §31-7 O18 |
| A10 Focus daily-pick | MERGE → O1 |

**Grok top-5 ship order (still valid for §31-1→§31-2):** O1+O2 → O5 → O4 → O3 → O7/O6

---

## Contract (each slice)

1. Branch `cursor/opt-<slug>-c3fd` off latest `main`
2. `pytest tests/test_endpoint_contract.py` green
3. No `data/*.json` commits
4. Update queue row on merge only
5. Auto-continue to next slice

## Token discipline

Cite slice ID + AC only. Full registry lives in this file. Grok LOCK only on fail.
