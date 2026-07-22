# Gameplan — Undeniable pump desk + site (post-#397)

**Status:** DRAFT for lock · **main:** `de1854f` (#397 pump self-learning shipped)  
**Date:** 2026-07-22  
**Owner default:** Agent `-4d53` (council/learning + pump desk) · Agent B for whales/flow when triad needs chain data  
**Peers scanned live:** SubnetAIQ Pre-Pump Radar, TAO Subnet Radar, TaoDashboard, TaoDX

---

## North star

Be the only Bittensor desk that **freezes a pre-pump claim, grades it honestly, shows n=, and adapts** — while speaking trader language (early / chase) and never lying about HOLD.

Do **not** clone full DEX / 128-row Bloomberg. Steal the five peer edges that make signals *believable*, then harden every home section so each answers **one trader question**.

---

## Design intent (internal — not public marketing)

**Private bar:** On-chain, the most profitable wallets are overwhelmingly bot-operated — speed, always-on scanning, zero hesitation. A human cannot clone that stack. This app exists so an **attentive human checking signals through the day** can theoretically **keep pace with bot-level outcomes** (timing, conviction, not missing the move).

**Do not sell this publicly.** “Beat the bots” sets expectations we cannot guarantee in copy. Hold the bar internally; keep external messaging grounded (graded claims, n=, hit rates, honest HOLD).

**Why these surfaces exist:**

| Surface | Trader job | Bot-parity role |
|---------|------------|-----------------|
| **Hero cards** | What to act on *now* | One-shot conviction without re-scanning 129 subnets |
| **Pump desk** | Intraday lead scanner | Catch flow before price — the window bots already exploit |
| **Horizons** | Multi-timeframe context | See the move bots are positioned for, not one candle in isolation |

**Build test:** Does this help someone who checks the app during the day act in time — not just understand after the fact?

---

## Hard rule — subnet display names (must hold site-wide)

**Rule:** Every user-visible subnet name **must** resolve through the canonical pipeline at **read time**. Never trust a name frozen in historical JSON (`predictions.json`, `daily_picks.json`, trail rows, etc.) on any live surface.

**Single source:** `internal/subnet_names.py` — `resolve_subnet_name()` / `name_for_netuid()` / `refresh_daily_pick_names()` / `refresh_stored_names()`.

**Resolution priority (today):**

1. Curator override — `config/subnet_name_overrides.json` (when upstream feeds lag a subnet rebrand)
2. Remote registry — GitHub `taostat/subnets-infos` `subnets.json` (**not** the TaoStats.io website)
3. TaoStats API identity — `api.taostats.io` (only when `use_taostats=True`; most hot paths skip for latency)
4. Local registry — `config/registry.json`
5. TaoMarketCap fallback → `SN{n}`

**Why overrides exist:** The TaoStats **website** can show the correct name while our **primary remote feed** (community GitHub JSON) still lists the **previous occupant** (e.g. SN15 `De-Val` vs **ORO**, SN28 `LOL` vs **gm**). That is a **stale static file**, not “the user is wrong.” Curator overrides are the surgical fix until upstream catches up or we reprioritize live TaoStats identity on hot paths.

**Surfaces in scope (non-exhaustive — verify on every new route/UI):**

- Hero / daily pick / horizon chips
- Pump desk cards
- Recent calls / story strip
- Weighed against, Living Focus, council votes
- Share pages, scanner tables, whale rows, mindmap trail
- Client hydrate (`resolveSubnetDisplayName` must prefer `/api/subnets` registry enriched by the resolver)

**Verification (required before merge when touching names or display paths):**

- [ ] `pytest tests/test_subnet_names.py` — resolver priority + override beats stale remote
- [ ] Any new panel that shows a subnet name calls resolver on read (or consumes an API that already does)
- [ ] No new `pred.get("name")` / `row.name` display without netuid re-resolve
- [ ] Phone QA: spot-check renamed netuids (SN15 **ORO**, SN28 **gm**) on hero + pump + recent calls after deploy

**Drift workflow (do not wait for user to notice):**

1. User report or QA flags wrong name → add override + test in `test_subnet_names.py`
2. Periodic audit (future automation): diff overrides + local registry vs GitHub `subnets.json` and flag mismatches
3. Optional upgrade: prefer TaoStats API identity over stale GitHub when API key live and response is fresh

---

## Already shipped (do not re-litigate)

| Slice | Main |
|-------|------|
| Hero hydrate + fast daily-pick | #393–#394 |
| Hero trust polish + `phase_at_prediction` | #395 |
| `pump_lead` ledger at phase entry | #396 |
| Claim grading (+2%/1h), trust line, `pump_calibration` adapt n≥30 | #397 |

**Gate before Wave 2:** Phone QA 390px after #397 deploy — trust line visible; daily-pick still &lt;2s; weighed-against varied %.

---

## Sequencing (optimal mix — no OR)

```
Wave 0  QA gate (#397 live)
  → Wave 1  Pump undeniable core (triad + hit-rate surface + size cliff)
    → Wave 2  Push + wallet chips (alerts + social proof)
      → Wave 3  Site section hardening (hero → letters → portfolio)
        → Wave 4  Depth / Pro (optional; never steal first viewport)
```

| Wave | What | Why this order |
|------|------|----------------|
| **0** | QA + trust line populated as grades land | Proof loop must be real before we advertise hit rates |
| **1** | Triad + published claim hit-rate UI + size cliff | Beat SubnetAIQ signal story + TaoDashboard proof + TaoDX execution honesty — without Telegram yet |
| **2** | Push alerts + lead-wallet / founder chips | Beat SubnetAIQ/TaoDX distribution; needs Wave 1 cards to hang chips on |
| **3** | Site sections (3 upgrades each, ranked) | Convert competitive site notes into shippable ACs after pump is undeniable |
| **4** | Pro depth / screener / risk polygons | Nice-to-have; peers win on breadth — we stay single-job home first |

---

## Wave 1 — Pump undeniable core

**Goal:** Lead scanner cards that look smarter than SubnetAIQ and more honest than Radar/TaoDashboard.

### P1 — Inflow + pressure + coil triad

| | |
|--|--|
| **Beat** | SubnetAIQ Pre-Pump Radar (explicit 3-leg recipe) |
| **Owner** | `-4d53` (+ Agent B if net TAO flow API lives in whales/analytics) |
| **Scope** | Per alert row: three booleans/lights — TAO inflow quiet-load, buy pressure ≥ gate, price coil (stabilize after drop). STRONG / full BUILDING only when 2–3 legs lit. Persist legs into frozen `signal_snapshot` for learning. |
| **Touch** | `internal/pump/signals.py`, `pump_alert.py`, ledger snapshot, card UI |
| **AC** | Card shows triad; STRONG requires all three; snapshot includes triad fields; unit tests for coil/inflow helpers |

### P2 — Published claim hit-rate as desk proof

| | |
|--|--|
| **Beat** | TaoDashboard homepage **59.5%** walk-forward brag |
| **Owner** | `-4d53` |
| **Scope** | Promote trust line: ready state shows big mono % + n + window; last-10 strip optional. Separate from council 33% banner. |
| **Touch** | `pump_lead_stats.py`, `pump_alert.html`, hydrate |
| **AC** | When `early.n ≥ 5`, line is primary subcopy; never mixed into council accuracy |

### P3 — Size cliff line

| | |
|--|--|
| **Beat** | TaoDX pool simulator / liquidity cliff |
| **Owner** | `-4d53` |
| **Scope** | One mono line under thesis: `50 τ ≈ X% of float · thin\|healthy\|deep` (reuse impact/float helpers). No full simulator. |
| **Touch** | `pump_alert.py` + card template/JS |
| **AC** | Every lead/confirmed card has size line or honest-empty when unpriced |

**Wave 1 exit:** Phone QA — triad lights + trust % + size line on 390px within hydrate budget.

---

## Wave 2 — Distribution + social proof

### P4 — Push on phase entry

| | |
|--|--|
| **Beat** | SubnetAIQ email/Telegram; TaoDX premium alerts |
| **Owner** | `-4d53` (Telegram H4 may share creds) |
| **Scope** | Env-gated: notify on BUILDING / JUST STARTED entry only (not CHASE RISK spam). Prefer Telegram bot or existing conviction-alerts pattern. |
| **AC** | One testable notify hook; default off; rate-limit per netuid |

### P5 — Lead-wallet + founder chips

| | |
|--|--|
| **Beat** | TaoDX Lead Wallets / Founder Insider |
| **Owner** | Agent B (`whales/*`) + `-4d53` UI |
| **Scope** | Chips only: “N wallets bought before move” / “owner added” when investigation APIs can support; honest-empty otherwise. |
| **AC** | Chip or empty; never fake wallets |

**Wave 2 exit:** Alert fires in staging; at least one live subnet shows a real wallet chip or honest empty.

---

## Wave 3 — Site sections (3 upgrades each)

Priority order = first viewport → retention. Each slice ships **all three ACs** or is not done.

### S1 — Daily Call / Council hero
1. Resolve countdown always set or honest “window pending — not graded yet”
2. One **vs hold TAO** (7d) line under thesis
3. Evidence = three tagged drivers (flow / tech / social), max 3

### S2 — Weighed against
1. Sort by proximity to call (not flat %)
2. Distinct why-not per row
3. Tap → mini compare (flow 24h, depth, emission)

### S3 — Living Focus
1. Empty state → nearest near-call + one trigger
2. Pin ↔ watchlist one tap
3. “Who sold” only when focus netuid set

### S4 — Letters / Brain / Recap
1. Open with one graded outcome from yesterday
2. New-subnet / seed strip (TaoDashboard-style, honest)
3. Copyable “today’s desk” block

### S5 — Paper portfolio
1. Avg-per-call headline (keep) + vs TAO always
2. HOLD / TAKE / EXIT cues on open rows
3. Last-10 closed only; no absurd cumulative hero number

### S6 — Track record / What’s working
1. Never contradict “455 graded”
2. Price-signal chips with n + hit rate
3. Tab: Council accuracy | Pump early hit-rate

### S7 — Council votes / Outcome / Judges
1. One flip-to-LONG sentence
2. Lifecycle strip filled from trail/resolver
3. Blockers deduped (maintain)

### S8 — Pro / whales / mindmap / footer
1. Pro behind single “Open depth” — home stays Call + Lead
2. Owner vs smart-money labels on whale rows
3. Footer metrics after tier-1 always &gt;0; source Live vs Snapshot clear

---

## Wave 4 — Optional depth (YAGNI until Waves 1–3 green)

- Full screener / risk polygons (SubnetRadar breadth)
- Autotrade / swap (TaoDX) — **out of scope** unless product lock changes
- Coil sparkline calendar, 30d chip — deferred polish from board

---

## Explicit non-goals

- Cloning TaoDX DEX or autotrade
- Mixing pump outcomes into council expert weights
- Adapting thresholds before honesty gate (n≥~30) — already coded; don’t weaken
- First-viewport dashboard of 12 cards

---

## Slice queue (implementation checklist)

| ID | Wave | Slice | Depends | Status |
|----|------|-------|---------|--------|
| G0 | 0 | Phone QA #397 | deploy | pending |
| P1 | 1 | Triad lights + snapshot | G0 | pending |
| P2 | 1 | Hit-rate proof UI | G0 | pending |
| P3 | 1 | Size cliff line | G0 | pending |
| P4 | 2 | Push on BUILDING/JUST STARTED | P1 | pending |
| P5 | 2 | Wallet/founder chips | P1 + whales API | pending |
| S1 | 3 | Hero 3 upgrades | Wave 1 | pending |
| S2 | 3 | Weighed against 3 | S1 | pending |
| S3 | 3 | Living Focus 3 | S1 | pending |
| S4–S8 | 3 | Remaining sections | S1 | pending |

**Parallelism:** P1∥P2∥P3 after G0. P4∥P5 after P1. S2∥S3 after S1.

---

## Success metrics

| Metric | Target |
|--------|--------|
| Early pump claim hit-rate published | Visible with n≥5; adapt continues at n≥30 |
| Lead card completeness | Triad + size line on ≥90% priced alerts |
| Hero hydrate | Orb + evidence + footer &lt;5s; weighed deferred OK |
| Phone QA | 390px: Call + Lead + trust line without Pro scroll |
| Differentiation | Competitors have signals; we have **graded claims + chase honesty** |

---

## Next action

1. Human: approve this gameplan (or mark CHANGES).  
2. Agent: run **G0** phone QA on prod after #397 deploy.  
3. On PASS: start **P1+P2+P3** on one branch or three thin PRs (prefer thin PRs).
