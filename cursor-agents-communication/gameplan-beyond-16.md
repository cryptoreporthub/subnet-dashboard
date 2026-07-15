# §17 — Beyond the trust gap (optimal mix)

**Status:** APPROVED mix 2026-07-15 · execution via `s16-s17-automated-build-plan.md` (after `GATE_S16`)  
**Depends on:** §16 Complete (`gameplan-phase-16.md`)  
**Companion:** what Ditto left out of the trust-gap slice · `s16-s17-start-prompts.md`

## Design rule

Mix complementary strengths. Do **not** pick one idea and discard the others — each bucket below is a **stacked** product: user-facing language + honest internals + one sharp enrichment + retention loop.

Analogies used below: Polymarket (clear conviction), TradingView (hero + optional panels), Nansen (labeled smart money), Robinhood/Coinbase (simple home), Stripe (explain the charge), Glassnode (alerts), fantasy / copy-trade lite (paper P&L), Morning Brew (digest).

---

## Sequencing (mixed, optimal — no OR)

```
§16 trust
  → S-core (bands + start magnitude + one enrichment badge)
  → U-home (single-job home + story strip) ∥ F-spine (watchlist + alerts)
  → F-accountability (paper portfolio) ∥ U-polish (CONDITIONALs + framing + light enhance)
  → F-brand (weekly letter) ∥ F-depth (streaming chat + live intel)
  → F4 domain (human) whenever ready (non-blocking)
```

| Wave | What lands | Why this order |
|------|------------|----------------|
| **0** | §16 | Numbers trustworthy first |
| **1** | S1 bands + S2 magnitude start + S3 one enrichment | Language users understand + real math underneath + one Nansen-style badge |
| **2** | U1 home + U2 story ∥ F1 watchlist + F2 alerts | Daily open-loop (what to look at + ping me) |
| **3** | F3 paper portfolio ∥ U3 polish | Accountability uses §16 grading; UI cleanup while portfolio ships |
| **4** | F4 weekly letter ∥ F5 streaming chat + F6 live intel | Brand + power-user depth after the habit loop exists |
| **any** | F7 custom domain (human) | Parallel; never blocks product waves |

---

## §17.S — Extra signals (**mix A + B + C**)

**Recommendation:** Stack them.

| Layer | From | Role | Site analogy |
|-------|------|------|--------------|
| **User-facing** | **B** | **Conviction bands** (high / med / low) from agreement + hit-rate — primary language in UI | Polymarket / Kalshi clarity |
| **Under the hood** | **A** | **Signal-derived magnitude** — kill confidence-proxy `%` for new predictions; feed hybrid_score when §16 gate allows | TradingView computed indicators, not decoration |
| **Enrichment** | **C** | **One killer badge** — e.g. whale/netflow or emissions shock when live; else honest-empty | Nansen / Arkham “smart money” label |
| **Channels** | (prior S3) | Optional Discord/X later; Telegram first | Discord communities as secondary firehose |

### Slices

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **S1** | A + B | **Conviction bands API + UI contract** — derive band from judge agreement + recent hit-rate; never invent mid band to look busy | `band ∈ {high,medium,low}` or null + reason; test for cold-start |
| **S2** | A | **Signal-derived `predicted_pct`** — replace `_predicted_pct_from_pick()` proxy for **new** rows | New predictions tagged non-proxy; test proves proxy path off for create |
| **S3** | B | **One enrichment badge** — pick **one** first (whale flow *or* emissions shock); wire into home + band context; honest-empty if feed down | Badge real or explicit empty; no fake “smart money” |
| **S4** | B | **Whale/rugger/indicator depth** — make existing CONTRACT routes useful or honest-empty (feeds S3) | One check per family |
| **S5** | A | **Optional Discord/X** — after Telegram path proven | Flagged off by default |

**How they fit:** Band is what humans read; magnitude is what graders/learn from; badge is the one glanceable “why this isn’t random.”

---

## §17.U — UI / experience (**true recommendation = mix B + C + A**)

**True recommendation:** Lead with a **single-job home** (B), add a **story strip** for trust (C), keep **polish + predictive framing** (A) as the quality floor — not a third redesign.

| Layer | From | Role | Site analogy |
|-------|------|------|--------------|
| **First viewport** | **B** | Today’s pick · conviction **band** · short why · CTA (alert / watchlist) | Robinhood / Coinbase simple home |
| **Trust path** | **C** | Timeline: signal → pick → resolve → learn (uses §16 outcomes) | Stripe “explain the charge” / Linear activity |
| **Everywhere else** | **A** | Finish CONDITIONALs, predictive copy, light progressive enhance; cockpit stays available as “Pro” | TradingView: hero first, panels optional |
| **Launch** | U4 | Custom domain polish when F7 ready | — |

### Slices

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **U1** | B | **Single-job home** — first viewport = pick + band + one sentence why + primary CTA; rest of cockpit demoted below fold or “Pro” | Brand-test: without nav, still SimiVision; no card sprawl in hero |
| **U2** | B | **Story strip** — compact timeline of last N picks with right/wrong from §16 | Shows real outcomes or honest empty |
| **U3** | B | **Polish + framing** — Phase-2 CONDITIONALs; predictive tense per `premium-dashboard-redesign.md`; surface hybrid or “not enough data yet” | Grok medium PASS or written waivers |
| **U4** | B | **Light enhance** — deepen SSE/htmx only on home refresh paths | One hot path no full reload |
| **U5** | B + Human | **Launch surface** on custom domain | Works when certs live |

**Out of U:** Neon theme rewrite, new cockpit panel count, marketing landing as a separate product.

---

## §17.F — Big features (**mix A + B + C + D**)

**Recommendation:** Retention spine first, accountability second, brand parallel, power-user depth last — all of them, staged.

| Layer | From | Role | Site analogy |
|-------|------|------|--------------|
| **Habit** | **B** | Watchlist + conviction alerts (Telegram/email) | Glassnode / CMC alerts |
| **Accountability** | **D** | Paper portfolio following council picks vs hold-TAO | eToro copy-trade lite / fantasy |
| **Brand** | **C** | Weekly digest letter (pick, win rate, 3 scenarios) | Morning Brew / research note |
| **Depth** | **A** | Streaming SimiVision chat + live message-intel | ChatGPT sidebar inside a terminal |
| **Launch** | Human | Custom domain | — |

### Slices

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **F1** | A + B | **Watchlist** — pin netuids; home + alerts respect it | Persist per browser or simple server store; honest empty OK |
| **F2** | A + B | **Alert delivery** — O1 backend → real Telegram and/or email; watchlist-aware | E2E notify; idempotent; flag-gated |
| **F3** | A + B | **Paper portfolio** — auto-follow resolved council picks; P&L vs hold TAO; uses §16 grading | Shows real resolved P&L or empty; no fake fills |
| **F4** | A + B | **Weekly letter** — markdown/email digest from existing stats + top pick | One generate endpoint + template; manual or cron |
| **F5** | A + B | **Streaming chat** — ASGI stream on `/api/simivision/chat`; XSS-safe | Stream works; contract updated |
| **F6** | A | **Live message-intel** — Telegram (then S5 Discord/X) when creds present | Non-empty when creds; honest-empty when not |
| **F7** | Human | **Custom domain** (`DEPLOY.md`) | HTTPS on `dashboard.cryptoreporthub.com` |

**Report depth (old F5):** only if users ask after letter + portfolio — YAGNI until then.

---

## Agent ownership

| Track | Primary |
|-------|---------|
| **S** | A (bands math, magnitude) + B (badge, whales/indicators, band UI contract) |
| **U** | B (`templates/*`, `static/*`) |
| **F** | A (alerts, chat, intel, portfolio engine) + B (UI) + Human (F7) |

**Conflict surface:** `server.py` includes + `tests/test_endpoint_contract.py`.

## Models

| Work | Model |
|------|-------|
| Lock band/magnitude/badge contracts | Grok slow + **medium** |
| Home + story UX | Grok slow + medium design → Composer → medium sign-off |
| Implement | Composer 2.5 |

## Phase-level acceptance

| # | Check |
|---|--------|
| 1 | §16 done (or explicit waive) before scores/bands shown as truth |
| 2 | Home shows **band** (not naked fake %); magnitude only when S2 live |
| 3 | Enrichment badge honest-empty when feed down |
| 4 | Watchlist + alerts ship before chat is “the” feature |
| 5 | Paper portfolio uses resolved §16 outcomes only |
| 6 | Honest-empty preserved everywhere |

## Non-negotiables

1. Honest-empty > decorative summaries > 500  
2. Never lower thresholds to fake accuracy  
3. Single foundation: `server:app`  
4. No `data/*.json` commit churn  
5. Do not revert N/O/P or Step 0  

## After §17

Idle / monitor. New sections only if Ditto opens them.
