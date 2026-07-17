# Website optimization plan — 20+ ideas (post-#316)

**Status:** READY · automated queue  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `a93f760`  
**Grok LOCK:** slow+low review of agent deep-dive (PASS · CONDITIONAL merges)  
**Out of scope:** H1 custom domain · H2–H6 human infra · D1–D7 deferred features

## Agent prompt

```
OPT-20 AUTOMATION:
- Read board.md → this file → active slice AC only.
- Branch: cursor/opt-<slug>-c3fd off latest main.
- Prefer S/M effort first (ship order below).
- No data/*.json · RF-2 · no custom domain.
- Grok only on AC fail / ambiguous design.
```

---

## Grok review of first 10

| # | Idea | Verdict | Note |
|---|------|---------|------|
| A1 | Homepage fetch storm | **KEEP / UPGRADE** | Dominates TTFB + churn |
| A2 | Wallet double `investigate_wallet` | **KEEP** | Clear double-call bug |
| A3 | Search `load_predictions` every keystroke | **KEEP** | Server reloads JSON each hit |
| A4 | Missing `Cache-Control` on heavy GETs | **KEEP** | Heavy paths uncached |
| A5 | Learning metrics triple disk I/O | **MERGE → A3** | Same predictions memo gap |
| A6 | 24 serial JS files / no bundle | **DOWNRANK** | `defer`+HTTP/2; storm first |
| A7 | Google Fonts `@import` blocking paint | **KEEP** | Easy FCP win |
| A8 | Command palette a11y | **DOWNRANK** | Real a11y; not ship-blocker |
| A9 | `get_merged_subnet` O(n) | **DOWNRANK** | Cached list; rarer hot path |
| A10 | `refreshFocus` re-fetches daily-pick | **MERGE → A1** | Same daily-pick fan-out |

---

## Full backlog (22 ideas)

### Tier 1 — Ship next (Grok top-5)

| ID | Title | Imp | Eff | Files | AC |
|----|-------|-----|-----|-------|-----|
| **O1** | Homepage fetch storm + Focus daily-pick dedupe | H | M | `cockpit_hydrate.js`, `living_focus.js`, `home_live_refresh.js` | One `HomeData` bus; Focus/live-refresh read cache; no cold double `/api/daily-pick` |
| **O2** | Kill SSE-tick + 60s dual refresh | H | M | `home_live_refresh.js`, `cockpit_hydrate.js`, cockpit SSE route | SSE tick does not also full-refetch `/api/subnets`; one refresh path |
| **O3** | Slim `/api/subnets` client fields | H | M | `server.py`, hydrate/live-refresh | Home uses `?fields=`/`limit`; payload ≪ full rows |
| **O4** | Unblock Google Fonts `@import` | M | S | `static/css/base.css`, share/home `<head>` | No CSS `@import` of fonts; preconnect + async or self-host |
| **O5** | Wallet share single investigate call | H | S | `internal/share_pages/routes.py` | One `investigate_wallet`; reuse for activity + flow |

### Tier 2 — Trust + cache (next PR)

| ID | Title | Imp | Eff | Files | AC |
|----|-------|-----|-----|-------|-----|
| **O6** | Search + predictions memo (A3+A5) | H | S | `search.py`, `learning/routes.py` | Skip pred scan if `len(q)<8`; 30–60s in-mem memo for `load_predictions` / learning snapshot |
| **O7** | `Cache-Control` map for heavy GETs | H | S | `server.py` | Path→TTL: subnets 300, council/judges 120, search 30, learning 60 |
| **O8** | Prod SN name integrity hard-fail | H | M | `subnet_names.py`, hydrate/share | APIs never emit null / `SNNone` display names |
| **O9** | `verify_prod` name + SSE + hydrate probes | M | S | `scripts/verify_prod.sh` | Assert no `SNNone`, SSE `once=1` 200, sample name |
| **O10** | Share OG / Twitter image meta | M | S | `templates/share/base_share.html`, share routes | `og:image` + `twitter:card=summary_large_image` on subnet/wallet |

### Tier 3 — UX / a11y / mobile

| ID | Title | Imp | Eff | Files | AC |
|----|-------|-----|-----|-------|-----|
| **O11** | Mobile Living Focus layout | M | S | `council_first.css`, `living_focus.html` | ≤640px judge grid readable, no horizontal crush |
| **O12** | Investigation seller→owner batch | M | M | `investigation_panel.js`, investigate routes | Owner-check one round-trip (or batched wallets) |
| **O13** | Story strip / path / Focus overlap | M | S | `premium_cockpit.html` | One narrative above fold; others collapsed/deferred |
| **O14** | Muted text contrast WCAG | M | S | `council_first.css`, `share_pages.css` | `--stage-muted` ≥ 4.5:1 on background |
| **O15** | Command palette a11y (A8) | M | S | `command_palette.js` | listbox + `aria-expanded` + `aria-activedescendant` |

### Tier 4 — Infra / polish (when touching area)

| ID | Title | Imp | Eff | Files | AC |
|----|-------|-----|-----|-------|-----|
| **O16** | Static asset fingerprint / longer TTL | M | M | `server.py`, static URL refs | Hashed or immutable assets safe post-deploy |
| **O17** | Bundle core home JS (A6) | M | M | `scripts.html`, build or concat | Core home ≤2–3 scripts; drawer modules lazy |
| **O18** | `get_merged_subnet` O(1) index (A9) | M | S | `fetchers/merged_data.py` | Netuid dict invalidated with SQLite TTL |
| **O19** | SQLite connection reuse in fetchers | M | M | `taomarketcap.py`, `merged_data.py`, `taostats_client.py` | Module-level WAL conn + lock; no connect-per-read |
| **O20** | Learning snapshot module cache | M | S | `internal/learning/routes.py` | One `_learning_snapshot()` ≤30s for stats/metrics/mindmap |
| **O21** | Share-page Lighthouse empty/error states | L | S | share templates + CSS | Honest empty + retry CTA when TaoStats dark |
| **O22** | CSS scroll-row dedupe | L | S | `council_first.css` | Shared `.simi-scroll-row` for story/portfolio/letter lists |

---

## Automated queue (sequential)

| # | Slice | IDs | State |
|---|-------|-----|-------|
| **§31-0** | Docs: this plan + board pointer | — | next |
| **§31-1** | Homepage data bus (storm + Focus) | O1, O2 | pending |
| **§31-2** | Wallet single investigate + fonts | O5, O4 | pending |
| **§31-3** | Cache headers + search/learning memo | O7, O6, O20 | pending |
| **§31-4** | Slim subnets + name integrity + verify_prod | O3, O8, O9 | pending |
| **§31-5** | Share OG + mobile Focus + contrast | O10, O11, O14 | pending |
| **§31-6** | Inv batch + narrative fold + palette a11y | O12, O13, O15 | pending |
| **§31-7** | Optional: static TTL, JS bundle, merged index | O16–O18 | pending · skip if Tier 1–3 enough |
| **§31-8** | Optional: SQLite reuse, empty states, CSS dedupe | O19, O21, O22 | pending · skip |

---

## Slice AC (Tier 1)

### §31-1 — Homepage data bus
- [ ] `window.HomeData` (or strengthen `HomeHydrateCache`) is single write from hydrate
- [ ] Living Focus cold path waits for cache event ≤2s before own fetch
- [ ] `refreshFocus` does not re-fetch daily-pick when cache fresh
- [ ] Live refresh does not double-fire on SSE tick + interval for same payload
- [ ] Contract + smoke still green

### §31-2 — Wallet + fonts
- [ ] Wallet page: one `investigate_wallet` call
- [ ] No `@import` fonts in `base.css`
- [ ] Share + home still load Rajdhani / JetBrains (or system fallback honest)

### §31-3 — Cache + memo
- [ ] Heavy GET paths have documented `Cache-Control`
- [ ] `/api/search` skips predictions for short queries
- [ ] Learning routes share ≤30s snapshot

---

## Non-goals

- Custom domain / CDN (H1)
- Telegram / Discord / email / listener creds
- Redis, Bittensor SDK, EMA nudge, full money-flow graph
- Full test-suite green for all historical modules (incremental only)

## Token discipline

Plan file is cache; cite IDs not re-paste. Grok only on AC fail. One slice per PR when unattended.
