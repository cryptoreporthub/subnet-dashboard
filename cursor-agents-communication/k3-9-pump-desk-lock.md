# K3-9 Pump Desk LOCK — Council-owned, predictive, graded

**Status:** LOCKED 2026-07-19 · Grok COPY/PRODUCT  
**Supersedes presentation of:** K3-8 / K3-8b horizontal scroll as primary UI  
**Keeps:** Lead-first phases (STIRRING/ACCUMULATING → PUMPING chase-risk → COOLING exit)  
**North star:** Not a crypto % ticker. Multi-name **desk** with **who called it**, **projected move**, **graded outcome**.

---

## VERDICT: PASS (product direction)

Horizontal cards are a warm-up. The product is a **Pump Desk**: ranked board of live lead/confirmed names, each a **council-stamped call** with projection + later grade.

---

## 1. Problem

| Today | Wanted |
|-------|--------|
| Scroll of status cards | Multi-subnet board (usually >1 active) |
| Ladder phase = UI truth | Ladder = **sensor**; council/judges = **authority** |
| No projected % | SciWeave-style `predicted_pct` at watch entry |
| No accountability | Hit projected / died early (**pump fake**) graded |
| Looks like every % feed | Predictive desk with track record |

---

## 2. Architecture (reuse, don't invent)

```
Pump ladder (sensor)          Council / judges (authority)         Ledger (accountability)
STIRRING / ACCUMULATING  →    score + stamp call               →   pump_calls.json
PUMPING / COOLING        →    update status / exit             →   resolve → grade
                              predicted_pct_from_score             hit | fake | miss
                              (SciWeave hybrid when ready)
```

| Piece | Existing | Role |
|-------|----------|------|
| Ladder phases | `internal/pump/*` | Detection only — when to consider a name |
| Lead gate | `buy_ratio ≥ 0.55`, `vol ≥ 0.22` | Same as K3-7b / K3-8b |
| Projection | `predicted_pct_from_score` / `attach_council_prediction` | % move + horizon at stamp |
| Judges | Oracle / Echo / Pulse | Optional dissent line on row |
| Expert weights | Quant / Hype / Dark Horse / Technical | Who drove the stamp |
| Grading | SciWeave `direction` + `magnitude_calibration` + hybrid | Outcome score when sample ≥ 30 |
| Predictions store | `data/predictions.json` | Prefer extend with `kind: pump_call` OR thin `data/pump_calls.json` |

**Decision:** Thin dedicated `data/pump_calls.json` first (clear schema, no resolver collision). Later merge into predictions if one ledger wins.

---

## 3. Call lifecycle

1. **WATCH** — first lead-qualified STIRRING/ACCUMULATING tick  
   - Stamp: `entry_price`, `predicted_pct`, `horizon_hours` (default **4h** for pump desk), `expert`, optional judge scores  
   - UI: still early — entry window open  
2. **BUILDING** — ACCUMULATING while call open  
3. **CONFIRMED** — ladder hits PUMPING (chase risk; call still open for grading)  
4. **RESOLVE** at horizon or early exit:  
   - `actual_pct` from entry → resolve price  
   - Classify outcome (below)  
5. **CLOSE** — COOLING or timeout with no hit

---

## 4. Thresholds & outcomes (pump fake)

Defaults (env-overridable later):

| Knob | Default | Meaning |
|------|---------|---------|
| `PUMP_HIT_RATIO` | **0.60** | `actual ≥ 0.60 × predicted` → **HIT** (achieved projected pump) |
| `PUMP_FAKE_FLOOR` | **+1.5%** | Must clear this from entry before counting as a real move attempt |
| `PUMP_FAKE_CEILING` | **0.40 × predicted** | Peaked above floor but never reached 40% of projected → **FAKE** |
| `PUMP_MISS` | else | Never cleared floor, or wrong direction |

Examples (`predicted = +6%`):

| Path | Grade |
|------|-------|
| Peak +6.2% within horizon | **HIT** |
| Peak +4.0% (≥ 60% of 6) | **HIT** |
| Peak +2.0% then died (cleared 1.5%, < 40% of 6 = 2.4%) | borderline — if peak < 2.4% → **FAKE**; if ≥ 2.4% but < 3.6% → still FAKE under ceiling rule; use HIT ratio for success only |
| Peak +1.2% then dump | **MISS** (never cleared 1.5% floor) |
| Peak +2.0% then dump (floor cleared, < 2.4% of projected) | **FAKE** |

**Copy (trader):**
- HIT → `Hit · +X% of +Y% projected`
- FAKE → `Pump fake · peaked +X% vs +Y% projected`
- MISS → `Miss · never cleared the +1.5% watch bar`

Lane accuracy strip (when ≥ 10 resolved pump calls):  
`Last N desk calls: H% hit · F% fake · M% miss`

---

## 5. Presentation (replace horizontal scroll)

**Primary UI: vertical ranked board** (390px-first), not carousel.

```
Lead desk                          Last 24 graded: 41% hit · 28% fake
─────────────────────────────────────────────────────────────────────
BUILDING  Apex SN99     +6.0% proj · 4h     Quant leads · Oracle 0.72
          Flow ahead of price · entry open
          [meter] watch→building→…          since 14:02

EARLY     Sub42 SN42    +3.5% proj · 4h     Hype leads
          Buy pressure building

CONFIRMED Coldint SN29  +5.0% proj · chase  Dark Horse · Pulse dissent
          Live — rotate, don't chase

EXIT      …             FAKE · peaked +1.8% vs +6%
```

Rules:
- Cap **8** open rows (LEAD first, then CONFIRMED, then EXIT/graded teaser max 2)
- One row = one call (not a pretty card stack)
- Tap → `/subnet/{id}` or Living Focus
- No hero competition with Daily Call dossier

---

## 6. Accountability fields (per row)

| Field | Source |
|-------|--------|
| `netuid`, `name` | Registry resolve |
| `status` | watch / building / confirmed / exit / graded |
| `predicted_pct`, `horizon_hours` | Council attach at stamp |
| `entry_price`, `stamped_at` | Ledger |
| `expert` | Dominant council expert |
| `judge_line` | Optional `Oracle 0.7 · Echo 0.4 · Pulse 0.6` |
| `actual_pct`, `peak_pct`, `outcome` | On resolve |
| `thesis` / `trigger` | K3-8b voice (lead vs chase) |

---

## 7. Slice queue (implement in order)

| Slice | Deliverable |
|-------|-------------|
| **K3-9a** | `pump_calls` ledger + stamp on lead entry + resolve/grade helpers + tests |
| **K3-9b** | Vertical desk UI replacing carousel; wire SSR + hydrate + preview |
| **K3-9c** | Attach real `predicted_pct` via council score path; accuracy strip |
| **K3-9d** | Judge line + weight nudge on HIT/FAKE (learning loop) |

Do **not** ship 9d before 9a–9c have live stamps on prod.

---

## 8. Explicit non-goals

- Replacing Daily Call / dossier
- Showing PUMPING as "buy now"
- Fake accuracy before min sample
- New ML model — reuse SciWeave + existing score → `predicted_pct`

---

## VERDICT: PASS

Next Composer action: **K3-9a** only unless human expands scope.
