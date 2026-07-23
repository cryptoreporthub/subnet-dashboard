# Pump desk — richer lead signals (research LOCK)

**Status:** RESEARCH LOCK · 2026-07-23  
**Purpose:** Back the next pump-desk feature work with papers + peer claims, then a shippable signal stack.  
**Scope:** Predict / surface **flow before price** for Bittensor subnet alpha moves — not a full CEX order-book clone.

---

## North-star claim (what “earlier” means)

A lead is useful only if it fires **before** the desk’s own +2%/1h grade window closes, and preferably while copy still says BUILDING / WARMING — not CHASE RISK.

Academic P&D work and microstructure both say the same thing: **aggressive buy flow and short-horizon returns lead price**; longer windows (24h volume alone) lag.

---

## Evidence base (papers + claims)

### A. Organized pumps leave pre-signal footprints

| Source | Claim | Implication for us |
|--------|--------|-------------------|
| **Xu & Livshits (2019)** — *The Anatomy of a Cryptocurrency Pump-and-Dump Scheme* (USENIX Security; [arXiv:1811.10109](https://arxiv.org/abs/1811.10109)) | RF model AUC > 0.9 predicting *which* coin gets pumped **before** Telegram announcement. Top features: **market cap**, **1h return**, short-horizon volume/returns; organizers often **accumulate before** naming the coin. | Prefer **1h (or finer) return + volume anomaly + size/float**; small/mid float names are more pumpable. |
| **La Morgia et al. (2020)** — *Pump and Dumps in the Bitcoin Era* (ICCCN; [arXiv:2005.06610](https://arxiv.org/abs/2005.06610)) | Real-time detection via abnormal **buy market orders** (“rush orders”) + volume/price; detection in **~25s**, F1 ~92% — beats price-only detectors (~30 min). | **Buy-aggressiveness / buy-ratio surge** is the strongest *onset* signal; price alone is late. |
| **La Morgia et al. (2023)** — *The Doge of Wall Street* | Same rush-order story at scale (~900 events); market buy orders + trading frequency dominate. | Keep **buy pressure** as a hard lead gate; do not replace with price momentum. |
| **Hamrick et al. / follow-ons** (surveyed in later P&D ML theses) | Low liquidity + high pre-event returns mark targets. | **Size cliff / float** already on cards — keep it in the score, not just UI. |
| **2025 ensemble P&D detection** ([arXiv:2510.00836](https://arxiv.org/pdf/2510.00836)) | Extreme class imbalance; SMOTE + XGBoost/LightGBM; high recall for rare events. | Our `pump_lead` ledger + hit-rate trust line is the right evaluation frame; adapt gates only at n≥30 (already shipped). |

### B. Microstructure: order flow leads short-horizon price

| Source | Claim | Implication for us |
|--------|--------|-------------------|
| **Cont, Kukanov & Stoikov (2014)** — *The Price Impact of Order Book Events* | **Order flow imbalance** has a near-linear link to short-horizon price change. | Ideal lead = net buy pressure over seconds–minutes; 24h aggregates dilute it. |
| **Cao et al.; Cartea et al.** (equity OBI literature; crypto replications e.g. ETHUSD studies) | Bid/ask **queue imbalance** predicts next mid moves on short horizons; signal decays fast. | If we ever get book depth for alpha pools, OBI is gold — otherwise approximate with **buy vs sell volume** + recent Δprice. |
| **Bitcoin LOB crash study** (Donier & Bouchaud / similar) | Aggressive order-flow imbalance + thin book liquidity precede violent moves. | **Volume intensity vs float/emission** (size cliff) is a liquidity proxy we already use — weight it in classification, not only copy. |

### C. Social / coordination channels (secondary, confirmatory)

| Source | Claim | Implication for us |
|--------|--------|-------------------|
| Xu & Livshits; La Morgia | Telegram/Discord **coordinate** pumps; chatter often rises with or just before the move. | Message-intel chatter is a **confirm** leg, not the primary lead (false positives from spam). |
| Industry (Nansen-style whale tracking; Cointelegraph “early pump” playbooks) | Exchange outflows / **wallet accumulation** and smart-money clustering precede retail price. | Our `WhaleIntelligenceService.get_subnet_flow` + lead-wallet chips (Wave 2 P5) are the Bittensor analogue — **wire into score**, not only UI chips. |

### D. Peer product claims (competitive, not academic)

| Peer | Public edge | Steal / don’t steal |
|------|-------------|---------------------|
| **SubnetAIQ Pre-Pump Radar** | Explicit 3-leg recipe (inflow / pressure / coil) | **Already mirrored** in `internal/pump/triad.py` — strengthen with real TAO inflow, not proxy-only |
| **TaoDX** | Lead wallets / founder insider chips | Wave 2 P5 — chips + score boost when data_available |
| **TaoDashboard** | Published hit-rate | Wave 1 P2 trust line — already framed |
| **Radar / Bloomberg clones** | Breadth | **Do not** — stay single-job lead scanner |

---

## Gap analysis — what we have vs what research demands

| Lead signal (research) | Current desk | Gap |
|------------------------|--------------|-----|
| Buy market-order / buy-ratio surge (La Morgia) | `buy_ratio` from TMC buy/sell 24h | Often **missing → defaults 0.5**; need live feed + **Δ buy_ratio vs own baseline** |
| 1h return / short return (Xu) | `momentum_1h` or `24h/8` proxy | Need **true 1h** (or 15m) from price history / feed |
| Volume anomaly vs baseline (Xu, La Morgia) | `volume_intensity` vs emission | Need **z-score vs rolling median** per SN, not only absolute |
| Market cap / float (Xu) | Size cliff line (UI) | Underweighted in `compute_composite_score` |
| Quiet accumulation before price (Xu pre-pump; triad inflow) | Triad `tao_inflow_quiet_load` | Proxy only; no **net TAO stake/flow** from chain |
| Smart wallets bought early (Nansen / TaoDX) | Wallet chip optional | **Not in composite score** |
| Social chatter (coordination papers) | `chatter_intensity` 10% weight | OK as confirm; keep capped |
| Order-book imbalance (Cont et al.) | None | **Hard** without pool book API — defer or approximate |

---

## Recommended signal stack (ship order)

Priority = (research strength × data we can get on Fly × ponytail).

### Tier 1 — Must for “earlier + better” (next slice)

1. **Short-horizon return feature (true 1h / 15m)**  
   - Backing: Xu (1h return top feature).  
   - Source: price series we already persist / TMC / chain feed.  
   - Use: replace `/8` proxy; raise weight of `mom_term` when real.

2. **Buy-pressure *delta* vs rolling baseline**  
   - Backing: La Morgia rush-order anomaly.  
   - Source: same buy/sell volumes, but `buy_ratio − median_7d` (or vs subnet cohort).  
   - Use: STIRRING gate on **surge**, not absolute 0.55 alone (absolute fails when feed returns 0.5).

3. **Volume z-score (per-netuid rolling)**  
   - Backing: Xu short-horizon volume; La Morgia volume growth.  
   - Source: persist last N scan snapshots in ladder or a tiny ring buffer.  
   - Use: enter STIRRING when z ≥ threshold even if absolute intensity is mid.

4. **Wire triad + float into composite score**  
   - Backing: SubnetAIQ recipe + Xu market-cap; Cont liquidity.  
   - Today triad is mostly badge; composite still ignores float sensitivity.  
   - Use: boost score when 2–3 triad legs lit **and** thin float; dampen deep books.

### Tier 2 — High value when data ready (Wave 2 alignment)

5. **Whale / early-mover flow into score**  
   - Backing: accumulation-before-pump (Xu organizers; Nansen).  
   - Source: `WhaleIntelligenceService.get_subnet_flow` — only when `data_available`.  
   - Use: +score when early_movers/alpha_whales count > 0; chip already planned.

6. **Net TAO inflow (stake / pool flow)**  
   - Backing: triad “inflow quiet-load”; Cont flow imbalance analogue on-chain.  
   - Source: Agent B whales/analytics / chain RPC — honest-empty if missing.  
   - Use: true inflow leg replaces buy_ratio proxy in triad.

### Tier 3 — Stretch (don’t block the desk)

7. **Order-book / pool depth imbalance** — Cont et al.; needs book API.  
8. **Telegram coordination detection** — La Morgia channel monitoring; heavy ops + Telethon (env-gated).  
9. **ML classifier (RF/XGBoost)** — Xu / 2025 ensemble; only after Tier 1 features + n≥100 graded leads.

---

## What we will *not* claim

- Academic P&D papers study **CEX coordinated pumps**, not Bittensor subnet alpha. Mechanisms transfer (flow before price, small float, rush buys); **hit rates will differ**.  
- No public “beat the bots” marketing (gameplan hard rule).  
- Order-book OBI claims are **seconds–minutes**; our desk refresh is minutes — we approximate, we don’t scalp.

---

## Evaluation contract (keeps the feature honest)

Reuse existing loop — do not invent a parallel truth:

1. Freeze `signal_snapshot` at phase entry (`pump_lead` ledger) — already.  
2. Grade +2% / 1h — already.  
3. Trust line n= / hit-rate — already.  
4. **New:** per-feature ablation log in snapshot (`features_used`: 1h_real | buy_delta | vol_z | whale_boost) so we can prove which lead actually predicted.

Adapt gates only via `pump_calibration` at n≥30 — never council `soul_map` weights.

---

## Proposed next engineering slice (after this LOCK)

**Slice L1 — Short-horizon lead features** (Agent A ownership for pump desk):

| Work | Files |
|------|--------|
| Persist rolling signal history (last ~24–48 scans per SN) | `internal/pump/state.py` or small `data/pump_signal_ring.json` |
| Compute `return_1h`, `buy_ratio_delta`, `volume_z` | `internal/pump/signals.py` |
| Blend into `compute_composite_score` + STIRRING gates | `internal/pump/engine.py`, `pump_calibration` defaults |
| Freeze new fields into ledger snapshot | `pump_lead_ledger.py` |
| Tests with synthetic pre-pump series | `tests/test_pump_lead_features.py` |

**Slice L2** — Whale boost + true inflow (needs Agent B data path).  
**Slice L3** — Push on BUILDING entry (Wave 2 P4) once L1 false-positive rate is tolerable.

---

## One-line verdict

Research says the desk wins by detecting **buy-flow anomalies + short-horizon returns on thin float before price runs** (Xu, La Morgia, Cont). We already speak that language (triad, buy_ratio, size cliff) but mostly on **stale/absolute 24h proxies**. The big-feature gap is **short-horizon + baseline-relative features wired into the score**, then whale/TAO inflow when the feed exists — graded by the ledger we already have.
