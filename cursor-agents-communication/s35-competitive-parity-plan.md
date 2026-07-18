# §35 — Competitive parity + differentiation plan

**Status:** LOCKED (Grok slow+low → Composer expand) · 2026-07-18  
**Grok verdict:** CONDITIONAL — gate heavy UI on Phase B worker split if hydrate still competes with jobs  
**Competitors:** [Subnet Radar](https://subnetradar.com) (free, 34-pillar Alpha Score, 8 radars) · [AlphaGap](https://www.alphagap.io) (Free / $49 / $99, aGap score, Oracle, auto-index Ultra)

## Positioning (one sentence)

**Win as the only graded, accountable council + whale/rug investigation desk** — not a free Subnet Radar clone or AlphaGap Ultra custodial index.

| They optimize for | We optimize for |
|-------------------|-----------------|
| Composite scores & dashboards | Graded picks with public track record |
| Dev-vs-price gap thesis | Council evidence chain + learning loop |
| Wallet leaderboards | Rugger-aware flow intelligence + investigation |

---

## Build gate

| Gate | Rule |
|------|------|
| **GATE_B** | Complete **Phase B** (Fly web+worker split per `docs/fly-web-worker-split.md`) before P1 leaderboard + radar UI slices that add hydrate load |
| **GATE_CONTRACT** | All 112 `tests/test_endpoint_contract.py` routes stay non-5xx |
| **GATE_PONYTAIL** | No new deps, no second server, minimal diff per slice |

---

## P0 — Foundation + moat visible (ship with / after Phase B)

### P0-1 · `trust-accountability-surface`

**Scope:** Trust banner, graded pick history, judge dissent, learning stats above the fold on cold load (not buried in Pro drawer).

| Touch | Action |
|-------|--------|
| `templates/partials/premium/council_stage.html` (or cockpit cards) | Daily pick + conviction + trust banner + graded count |
| `static/js/trust_banner_ui.js` | Fail-visible when stats unavailable |
| `static/js/cockpit_hydrate.js` | Priority hydrate: trust → pick → whales before Pro drawer |
| `internal/learning/trust_stats.py` | Already exists — wire to first paint |
| `tests/test_phase_h_ui.py` | Assert trust strip in HTML shell |

**AC:** First meaningful content < 3s on cold deploy; trust banner shows graded count or explicit empty; daily pick visible without opening Pro drawer.

---

### P0-2 · `flow-flip-ruggers-desk`

**Scope:** Smart-money flow flips + rug risk as first-class UI — beat SR on intel depth, not wallet count.

| Touch | Action |
|-------|--------|
| `internal/whales/service.py` | Add `detect_flow_flips()` — 24h net flow sign change per subnet (ponytail: scan recent events, O(n) per subnet) |
| `internal/whales/routes.py` | `GET /api/whales/flow-signals` — flips + surges + net flow summary |
| `internal/ruggers/routes.py` | Surface active rugger count per subnet on same payload |
| `templates/partials/premium/investigation.html` | Flow signal strip (reuse whale/rug desk cards) |
| `static/js/investigation_panel.js` | Render flip cards with subnet link + council badge hook |
| `internal/whales/enrichment_badge.py` | Extend daily-pick badge: flip green + no ruggers |
| `tests/test_whales.py` (or new thin test) | Flip detection self-check on synthetic events |

**AC:** Investigation desk shows ≥1 flow flip or honest-empty; daily pick badge reflects whale+ruggers; API returns in < 500ms from cache.

**Non-goal:** 5k-wallet P&L leaderboard (SR scale) — defer to P2 research.

---

### P0-3 · `cold-hydrate-ux`

**Scope:** Hydrate fills or fails visibly in ~30s; no silent 0% KPIs (board Phase A success metric).

| Touch | Action |
|-------|--------|
| `static/js/cockpit_hydrate.js` | Per-section timeout + error chip |
| `static/js/data_freshness.js` | Stale-source badges on KPI zeros |
| `templates/partials/cockpit_cards.html` | Loading → error → data states |
| `internal/cockpit/routes.py` | SSE stream already exists — ensure error events |

**AC:** Any failed section shows labeled error within 30s; KPI row never shows `0%` without a "warming" or "unavailable" label.

---

### P0-4 · `fly-web-worker-split` (board Phase B — prerequisite)

**Scope:** Background jobs off HTTP path. See `docs/fly-web-worker-split.md`.

| Touch | Action |
|-------|--------|
| `internal/worker.py` | Resolver, registry sync, live feed warmup |
| `fly.toml` | `[processes] web` + `worker` |
| `server.py` | `RUN_MODE=web` skips background threads |
| `DEPLOY.md` | RUN_MODE docs |

**AC:** `/health` < 2s under hydrate storm; worker process runs resolver; web serves `/` without boot threads.

---

## P1 — Parity where backend already exists (post GATE_B)

### P1-1 · `composite-leaderboard`

**Scope:** Ranked subnet table from graded + council signals — **not** a 34-pillar SR clone.

**Pillars (reuse existing APIs):**
1. Council score (daily/hour state vector)
2. Judge consensus (Oracle + Echo + Pulse)
3. Whale flow (net + flip)
4. Rugger risk (inverse)
5. Indicator convergence
6. Learning-loop accuracy weight (trust)

| Touch | Action |
|-------|--------|
| `internal/analytics/composite_score.py` | **New** — thin composer over existing feeds |
| `internal/analytics/routes.py` | `GET /api/leaderboard` + Trading/Investing weight presets |
| `templates/partials/premium/scanner.html` or new partial | Sortable table, pillar drill-down on click |
| `static/js/premium_scanner.js` | Wire leaderboard; Trading/Investing toggle |
| `tests/test_endpoint_contract.py` | Add route to CONTRACT |

**AC:** 128 rows ranked; Trading vs Investing changes order; each row links to `/subnet/{id}` with pick history; pillar breakdown on subnet page.

---

### P1-2 · `graded-chat-beat-ag`

**Scope:** SimiVision chat answers with grades + investigation context — beat AlphaGap Oracle on accountability.

| Touch | Action |
|-------|--------|
| `internal/simivision/chat.py` | Inject: trust banner, pick explain, last 3 graded outcomes, investigation summary |
| `templates/partials/premium/chat.html` | Example queries: "Why today's pick?", "Rugger risk on SN44?", "Council win rate?" |
| `static/js/chat_stream.js` | Show cited sources (pick id, grade, whale event) |
| Rate limit | Keep 30/min; document as future Pro gate |

**AC:** Chat response cites ≥1 graded outcome or investigation fact when asked about a subnet; no fabricated grades.

---

### P1-3 · `telegram-alerts-thin`

**Scope:** Outbound alerts only — council pick change, flow flip, rugger on watchlist. Not a full SR bot.

| Touch | Action |
|-------|--------|
| `internal/conviction_alerts/` | Extend delivery (telegram path exists per §18 A1) |
| `internal/alerts/` or new `internal/telegram_notify.py` | Thin sender: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALERT_CHAT_ID` |
| Trigger hooks | Daily pick change, `flow-signals` flip, watchlist rugger hit |
| `DEPLOY.md` | Document secrets (human Fly step) |

**AC:** One alert type delivered end-to-end in staging; status endpoint shows configured/unconfigured honestly.

---

### P1-4 · `radar-chart-upgrade`

**Scope:** Replace heuristic 5-axis "Subnet Radar" with flow + conviction instruments.

| Touch | Action |
|-------|--------|
| `templates/partials/premium/radar.html` | Drop emission-top3 heuristic; hydrate from `/api/whales/flow-signals` + judges |
| `static/js/uplot_charts.js` | Multi-series: flow, conviction, rug risk per top pick |
| Remove `heuristic-tag` | Replace with `src-tag` showing real API sources |

**AC:** Radar section data comes from whale/judge APIs; empty state when APIs unavailable.

---

## P2 — Soft monetization + optional depth

### P2-1 · `tier-gates`

**Scope:** Feature flags only — no Stripe until human approves.

| Free | Pro (future ~$49) |
|------|-------------------|
| Leaderboard + top pick + trust strip | Unlimited SimiVision chat |
| Basic subnet pages | Full investigation desk |
| | Flow flip alerts + Telegram |
| | Whale dimension drill-down |

| Touch | Action |
|-------|--------|
| `config/feature_tiers.json` or env flags | `TIER=free|pro` |
| Gate middleware | 402-style JSON on gated routes when `TIER=free` |

**AC:** Flags documented; UI shows upgrade hint on gated features; no payment infra required for slice.

---

### P2-2 · `github-dev-radar-lite` (optional)

**Scope:** GitHub commit velocity strip on subnet page — thin, not SR Dev Radar clone.

| Touch | Action |
|-------|--------|
| `internal/freshness.py` | Already syncs `github` from taostat subnets-infos |
| `internal/analytics/report.py` | Add dev activity line to subnet report |
| Subnet share page | "Last known repo" + link |

**AC:** Subnet page shows repo link or "no public repo" flag.

---

### P2-3 · `comparison-strip` (optional)

**Scope:** 2–3 subnet side-by-side from existing APIs (not SR 4-way tool).

| Touch | Action |
|-------|--------|
| `static/js/premium_scanner.js` | Multi-select → comparison modal |
| Data | Reuse `/api/judges/{netuid}` + whale flow |

---

## Explicit non-goals (do not build in §35)

- Custodial auto-index / TrustedStake rebalance (AlphaGap Ultra)
- Full TAO Pages directory clone
- 34-pillar Alpha Score / 8-radar instrument parity
- Halving countdown radar
- Staking simulator
- Real user portfolio tracker (paper portfolio stays)
- 5k-wallet P&L leaderboard at SR scale
- Second server or new runtime foundation

---

## Slice queue (sequential)

| # | Slice | Depends | Owner |
|---|-------|---------|-------|
| 1 | P0-4 `fly-web-worker-split` | — | Infra |
| 2 | P0-3 `cold-hydrate-ux` | — | UI |
| 3 | P0-1 `trust-accountability-surface` | P0-3 | UI |
| 4 | P0-2 `flow-flip-ruggers-desk` | — | B track (whales) |
| 5 | P1-1 `composite-leaderboard` | GATE_B | B track |
| 6 | P1-4 `radar-chart-upgrade` | P0-2, P1-1 | UI |
| 7 | P1-2 `graded-chat-beat-ag` | P0-1 | A track |
| 8 | P1-3 `telegram-alerts-thin` | P0-2, human secrets | A track |
| 9 | P2-1 `tier-gates` | P1 complete | Product |
| 10 | P2-2/3 optional | — | Backlog |

**Branch template:** `cursor/s35-<slice>-aa9c`  
**Model:** Composer 2.5 (slow) for builds; Grok subagent only if slice marked DESIGN.

---

## Success metrics (vs competitors)

| Metric | SR | AG | Us (target) |
|--------|----|----|-------------|
| Time to first actionable view | ~20s | Gated | < 30s cold, pick + trust visible |
| Score explainability | 34 pillars | aGap 4 pillars | 6 pillars + graded outcome link |
| Whale intelligence | Flow flips, 5k wallets | Whale icon | Flow flips + **ruggers** + investigation |
| AI chat | Briefs | Oracle $49 | Graded chat with pick history |
| Alerts | Free Telegram | Premium Telegram | Council-event alerts |
| Accountability | None | Testimonials | Public graded track record |

---

## References

- Competitive analysis thread (2026-07-18) · Ditto memory `8f8eb7df`
- `docs/fly-web-worker-split.md` — Phase B architecture
- `cursor-agents-communication/board.md` — active Phase B
- `cursor-agents-communication/s18-automated-build-plan.md` — Telegram alert secrets pattern
