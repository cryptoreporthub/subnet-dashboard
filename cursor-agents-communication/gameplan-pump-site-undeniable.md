# Gameplan — Undeniable pump desk + site (post-#397)

**Status:** ✅ **Waves 0–3 shipped on `main`** (audited 2026-07-24) · Wave 4 YAGNI  
**main:** `6ee7d0d` (#437 Fly Phase B + post-#410 follow-ups)  
**Date:** 2026-07-22 (plan) · **status sync:** 2026-07-24  
**Owner default:** Agent `-4d53` (council/learning + pump desk) · Agent B for whales/flow when triad needs chain data  
**Execution:** PR **#410** (`cursor/full-plan-execution-c9f5`, Cursor Cloud Agent, merged 2026-07-22) + follow-up PRs #430–#437, #442–#446  
**Peers scanned live:** SubnetAIQ Pre-Pump Radar, TAO Subnet Radar, TaoDashboard, TaoDX

**Legend:** ✅ done · ⚠️ partial (code shipped; prod/ops gap) · ❌ not started · — YAGNI / out of scope

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

## Hard rule — design intent must hold site-wide

This intent is not aspirational copy. It is the **acceptance bar for every feature, section, and PR**. If a surface does not help an attentive human act in time, it does not belong on the home path — or it must be reframed / cut.

**The rule:** Every shipped surface answers: *“If I check this app during the day and follow the signals, does this help me keep pace with what bots are already doing?”*

| Must | Must not |
|------|----------|
| Actionable now (hero, pump phase, horizon chip) | Dashboard noise that only explains yesterday |
| Honest timing (early / chase / HOLD) | Hype that implies guaranteed bot-beating returns |
| Proof that builds trust (n=, graded claims, hit rates) | Vanity metrics with no decision hook |
| One clear trader question per section | Bloomberg clone / 128-row screener on first viewport |

**Surfaces governed by this rule (verify on every change):**

- **Hero** — single conviction call + evidence; not a research report
- **Pump desk** — intraday lead with phase honesty; not lagging price chase
- **Horizons** — multi-timeframe “where is the move”; not decorative chips
- **Weighed against / Living Focus** — why act or wait *today*
- **Track record / trust lines** — proof to act, not brag sheet
- **Wave 3 sections** — each must map to the build test above before ship

**Verification (required before merge when touching home, pump, horizons, or trader-facing copy):**

- [x] Can a user checking once in the morning and once mid-afternoon make a timed decision from this surface alone? *(shipped — hero + pump + horizons; ongoing prod tuning)*
- [x] Does copy stay grounded (no public “beat the bots” promise)? *(no public bot-beating copy in templates)*
- [x] Does the feature connect to hero, pump, or horizons — or justify why it lives elsewhere?
- [ ] Phone QA 390px: Call + Lead + at least one horizon path scannable without Pro scroll *(G0 script green; **human sign-off still open**)*

**Anti-patterns (reject in review):**

- Analytics that require constant monitoring to be useful but give no alert/phase hook
- Sections that duplicate TaoDashboard breadth without a faster *act* path
- Features that only make sense if you already run a bot

---

## Subnet display names (operational — separate from design intent)

Names must be trustworthy (wrong label = broken trust on an action surface). Not the north-star rule above — but still required hygiene.

**Pipeline:** `internal/subnet_names.py` — resolve at read time; never trust frozen JSON labels on live surfaces.

**Priority (today):** curator override → GitHub `taostat/subnets-infos` `subnets.json` → TaoStats API (when enabled) → local registry → TMC → `SN{n}`.

**Why overrides exist:** TaoStats **website** can be correct while the **GitHub JSON** we fetch still lists the previous occupant (e.g. SN15 `De-Val` vs **ORO**). Overrides in `config/subnet_name_overrides.json` until upstream catches up.

**When names drift:** add override + test in `test_subnet_names.py`; spot-check hero + pump + recent calls after deploy.

---

## Already shipped (do not re-litigate)

| Slice | Main |
|-------|------|
| Hero hydrate + fast daily-pick | #393–#394 |
| Hero trust polish + `phase_at_prediction` | #395 |
| `pump_lead` ledger at phase entry | #396 |
| Claim grading (+2%/1h), trust line, `pump_calibration` adapt n≥30 | #397 |

**Gate before Wave 2:** Phone QA 390px after #397 deploy — trust line visible; daily-pick still &lt;2s; weighed-against varied %.  
**Gate status (2026-07-24):** ⚠️ `scripts/g0_phone_qa.sh` ships SSR + triad API checks (#410); manual 390px pass not recorded on board.

---

## Completion ledger (audited vs `main` @ `6ee7d0d`)

| Wave | Slice | Status | Evidence on `main` |
|------|-------|--------|-------------------|
| 0 | **G0** Phone QA | ⚠️ | `scripts/g0_phone_qa.sh`; automated prod checks in #410; human 390px QA open |
| 1 | **P1** Triad + snapshot | ✅ | `internal/pump/triad.py`, `pump_alert.py`, UI + `tests/test_pump_wave1.py` |
| 1 | **P2** Hit-rate proof UI | ✅ | `pump_lead_stats`, trust line, proof-band Pump tab |
| 1 | **P3** Size cliff line | ✅ | `_size_cliff_line` → `50 τ ≈ X% of float` on cards |
| 2 | **P4** Push on phase entry | ✅ | `pump_phase_notify.py`, env-gated, `tests/test_pump_phase_notify.py` |
| 2 | **P5** Wallet / founder chips | ⚠️ | `wallet_chip` (smart-money flow) ✅; `whale_day_chips` (#430–#436) ⚠️ prod fill; **founder/owner chip** not shipped |
| 3 | **S1** Hero 3 upgrades | ✅ | `vs_hold_tao`, `evidence_drivers` (≤3), resolve countdown / window pending |
| 3 | **S2** Weighed against 3 | ✅ | Proximity sort, distinct why-not, tap → mini compare (flow/depth/emission) |
| 3 | **S3** Living Focus 3 | ⚠️ | Near-call empty ✅; pin ↔ watchlist ✅; “who sold” → **Prove it** button only when focus set ⚠️ |
| 3 | **S4** Letters / Brain | ✅ | `yesterday_outcome`, `seed_strip`, copyable desk block |
| 3 | **S5** Paper portfolio | ✅ | vs TAO compare, HOLD/TAKE/EXIT cues, last-10 closed |
| 3 | **S6** Track record | ✅ | Proof band Council \| Pump tabs; chips show n + hit% |
| 3 | **S7** Council votes | ✅ | Flip-to-LONG sentence, lifecycle strip, blockers deduped |
| 3 | **S8** Pro / footer | ✅ | “Open depth” CTA; owner vs smart-money labels; footer Live vs Snapshot |
| 4 | Depth / screener | — | YAGNI — not started by design |

**Post-#410 follow-ups (not in original slice table):**

| PR range | What | Status |
|----------|------|--------|
| #430–#436 | Day-whale + slip chips, TaoStats ingest, bg-scan CI fix | ✅ merged |
| #437 | Fly Phase B: `BACKGROUND_ON_WEB=essential` + worker process | ✅ merged |
| #442–#446 | Subnet integration badges, dossier crumbs, brain letter strip | ✅ merged |

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

### P1 — Inflow + pressure + coil triad ✅

| | |
|--|--|
| **Beat** | SubnetAIQ Pre-Pump Radar (explicit 3-leg recipe) |
| **Owner** | `-4d53` (+ Agent B if net TAO flow API lives in whales/analytics) |
| **Scope** | Per alert row: three booleans/lights — TAO inflow quiet-load, buy pressure ≥ gate, price coil (stabilize after drop). STRONG / full BUILDING only when 2–3 legs lit. Persist legs into frozen `signal_snapshot` for learning. |
| **Touch** | `internal/pump/signals.py`, `pump_alert.py`, ledger snapshot, card UI |
| **AC** | ✅ Card shows triad; STRONG requires all three; snapshot includes triad fields; unit tests for coil/inflow helpers (`tests/test_pump_wave1.py`) |

### P2 — Published claim hit-rate as desk proof ✅

| | |
|--|--|
| **Beat** | TaoDashboard homepage **59.5%** walk-forward brag |
| **Owner** | `-4d53` |
| **Scope** | Promote trust line: ready state shows big mono % + n + window; last-10 strip optional. Separate from council 33% banner. |
| **Touch** | `pump_lead_stats.py`, `pump_alert.html`, hydrate |
| **AC** | ✅ When `early.n ≥ 5`, line is primary subcopy; council accuracy stays in proof band tab |

### P3 — Size cliff line ✅

| | |
|--|--|
| **Beat** | TaoDX pool simulator / liquidity cliff |
| **Owner** | `-4d53` |
| **Scope** | One mono line under thesis: `50 τ ≈ X% of float · thin\|healthy\|deep` (reuse impact/float helpers). No full simulator. |
| **Touch** | `pump_alert.py` + card template/JS |
| **AC** | ✅ Every lead/confirmed card has size line or honest-empty when unpriced |

**Wave 1 exit:** ⚠️ Phone QA — triad lights + trust % + size line on 390px within hydrate budget *(G0 script covers API; manual 390px sign-off open)*.

---

## Wave 2 — Distribution + social proof

### P4 — Push on phase entry ✅

| | |
|--|--|
| **Beat** | SubnetAIQ email/Telegram; TaoDX premium alerts |
| **Owner** | `-4d53` (Telegram H4 may share creds) |
| **Scope** | Env-gated: notify on BUILDING / JUST STARTED entry only (not CHASE RISK spam). Prefer Telegram bot or existing conviction-alerts pattern. |
| **AC** | ✅ Testable notify hook (`pump_phase_notify.py`); default off; rate-limit per netuid |

### P5 — Lead-wallet + founder chips ⚠️

| | |
|--|--|
| **Beat** | TaoDX Lead Wallets / Founder Insider |
| **Owner** | Agent B (`whales/*`) + `-4d53` UI |
| **Scope** | Chips only: “N wallets bought before move” / “owner added” when investigation APIs can support; honest-empty otherwise. |
| **AC** | ⚠️ `wallet_chip` + `whale_day_chips` ship; honest-empty when no ledger data; **founder/owner-added chip** not implemented |

**Wave 2 exit:** ⚠️ Alert hook fires in dry-run tests; live whale chips depend on TaoStats warm + ledger ingest (#430–#437).

---

## Wave 3 — Site sections (3 upgrades each)

Priority order = first viewport → retention. Each slice ships **all three ACs** or is not done.

### S1 — Daily Call / Council hero ✅
1. ✅ Resolve countdown always set or honest “window pending — not graded yet”
2. ✅ One **vs hold TAO** (7d) line under thesis
3. ✅ Evidence = three tagged drivers (flow / tech / social), max 3

### S2 — Weighed against ✅
1. ✅ Sort by proximity to call (not flat %)
2. ✅ Distinct why-not per row
3. ✅ Tap → mini compare (flow 24h, depth, emission)

### S3 — Living Focus ⚠️
1. ✅ Empty state → nearest near-call + one trigger
2. ✅ Pin ↔ watchlist one tap
3. ⚠️ “Who sold” only when focus netuid set — **Prove it** button exists; not a standing chip

### S4 — Letters / Brain / Recap ✅
1. ✅ Open with one graded outcome from yesterday
2. ✅ New-subnet / seed strip (TaoDashboard-style, honest)
3. ✅ Copyable “today’s desk” block

### S5 — Paper portfolio ✅
1. ✅ Avg-per-call headline (keep) + vs TAO always
2. ✅ HOLD / TAKE / EXIT cues on open rows
3. ✅ Last-10 closed only; no absurd cumulative hero number

### S6 — Track record / What’s working ✅
1. ✅ Never contradict “455 graded” (proof band uses live `cal_n`)
2. ✅ Price-signal chips with n + hit rate
3. ✅ Tab: Council accuracy | Pump early hit-rate

### S7 — Council votes / Outcome / Judges ✅
1. ✅ One flip-to-LONG sentence
2. ✅ Lifecycle strip filled from trail/resolver
3. ✅ Blockers deduped (maintain)

### S8 — Pro / whales / mindmap / footer ✅
1. ✅ Pro behind single “Open depth” — home stays Call + Lead
2. ✅ Owner vs smart-money labels on whale rows
3. ✅ Footer metrics after tier-1 always &gt;0; source Live vs Snapshot clear

---

## Wave 4 — Optional depth (YAGNI until Waves 1–3 green) —

- Full screener / risk polygons (SubnetRadar breadth) — **not started**
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
| G0 | 0 | Phone QA #397 | deploy | ⚠️ script ✅ · human 390px open |
| P1 | 1 | Triad lights + snapshot | G0 | ✅ #410 |
| P2 | 1 | Hit-rate proof UI | G0 | ✅ #410 |
| P3 | 1 | Size cliff line | G0 | ✅ #410 |
| P4 | 2 | Push on BUILDING/JUST STARTED | P1 | ✅ #410 |
| P5 | 2 | Wallet/founder chips | P1 + whales API | ⚠️ wallet + day-whale (#430–#436); founder chip open |
| S1 | 3 | Hero 3 upgrades | Wave 1 | ✅ #410 |
| S2 | 3 | Weighed against 3 | S1 | ✅ #410 |
| S3 | 3 | Living Focus 3 | S1 | ⚠️ #410 (who-sold = Prove-it button) |
| S4 | 3 | Brain letter 3 | S1 | ✅ #410 |
| S5 | 3 | Paper portfolio 3 | S1 | ✅ #410 |
| S6 | 3 | Track record 3 | S1 | ✅ #410 |
| S7 | 3 | Council votes 3 | S1 | ✅ #410 |
| S8 | 3 | Pro/footer 3 | S1 | ✅ #410 |

**Parallelism:** P1∥P2∥P3 after G0. P4∥P5 after P1. S2∥S3 after S1. *(All merged; remaining work is ops + P5 founder chip + G0 human QA.)*

---

## Success metrics

| Metric | Target | Status (2026-07-24) |
|--------|--------|---------------------|
| Early pump claim hit-rate published | Visible with n≥5; adapt continues at n≥30 | ✅ UI + `pump_calibration` on `main` |
| Lead card completeness | Triad + size line on ≥90% priced alerts | ✅ code; ⚠️ prod depends on priced ladder rows |
| Hero hydrate | Orb + evidence + footer &lt;5s; weighed deferred OK | ✅ Phase A load-shed + #437 essential background |
| Phone QA | 390px: Call + Lead + trust line without Pro scroll | ⚠️ G0 script; human pass not logged |
| Differentiation | Competitors have signals; we have **graded claims + chase honesty** | ✅ shipped |

---

## Next action

1. ~~Human: approve this gameplan~~ — **locked; Waves 1–3 executed via #410.**
2. **Human:** run `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh` + 390px manual sign-off → close G0 on board.
3. **Ops:** `fly scale count worker=1` when ready for full live-feed worker (#437); verify whale chips on pump desk after warm.
4. **Optional slice:** P5 founder/owner chip (investigation API) if product wants TaoDX parity.
5. **Wave 4:** remain YAGNI until G0 + P5 gaps closed.
