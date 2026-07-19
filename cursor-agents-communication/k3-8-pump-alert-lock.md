# K3-8 Pump Alert LOCK (COPY/PRODUCT)

**Status:** LOCKED 2026-07-19 · Grok COPY/PRODUCT  
**main context:** `9028a84`+ (K3-7/7b shipped) · Composer implements from this LOCK only  
**Mobile:** 390px first · Trader voice, not audit log

---

## VERDICT: PASS

## DECISIONS

1. **Placement:** New section **between** `#section-daily-pick` (dossier) and `#section-living-focus`. Include order in `premium_cockpit.html`: `council_stage` → **`pump_alert`** → `living_focus`. Not inside dossier; not in Pro drawer.
2. **Hierarchy vs SimiVision hero:** Dossier remains sole first-viewport hero (brand + Daily Call). Pump Alert is a **secondary lane** — compact section title + rows, no orb/brand competition, no PUMPING chip on dossier (K3-7b unchanged: STIRRING/ACCUMULATING only).
3. **Source of truth:** Ladder `phase == PUMPING` (primary). Optional trailing row(s) for `COOLING` (demoted tone). Cap **5** PUMPING + **2** COOLING. Sort by `composite_score` / `final_score` desc. Reuse `internal.pump.state` / existing phase APIs — do not invent a second ladder.
4. **Independence:** Alert lane is **not** gated on council pick/candidate. Names may differ from Daily Call. Do not attach alerts onto `daily_pick` / `pump_chip`.
5. **Copy shape mirrors dossier brief** (move / thesis / trigger) + phase badge — not audit fields.

---

## 1. Section placement

| Slot | Role |
|------|------|
| `#section-daily-pick` | Tier 1 Daily Call + Session chip + early-heat chip |
| **`#section-pump-alert`** | Tier 3 Pump Alert — **this slice** |
| `#section-living-focus` | Council contention / focus |

- Eyebrow/title: **Pump Alert** / one sub: `Names already in motion — not the 24h call.`
- `data-home-live` OK if hydrate patches `#pump-alert-body` by ID (same patch-by-ID rule as K3-7; do not wipe dossier).

---

## 2. Card/row shape (per alert)

One **row** (interaction container OK; no hero cards). Fields:

| Field | Role | Example |
|-------|------|---------|
| `move` | Primary line | `IN PLAY · Apex (SN99)` |
| `thesis` | Why now (≤2 short sentences) | Flow + volume already hot; ladder in PUMPING. |
| `trigger` | What to do / watch | Chase risk — size only if you accept late entry. |
| `badge` | Phase label | `PUMPING` or `FADING` (COOLING) |
| `score` | Compact mono | e.g. `0.71` (optional; hide if null) |

Row chrome: netuid/name left-ish; badge right; thesis+trigger stacked under move. 390px: single column, tap target ≥44px height.

---

## 3. Copy patterns

**PUMPING (required):**
- move: `IN PLAY · {Name} (SN{n})` — if name is `SN{n}` only, use `IN PLAY · SN{n}`
- badge: `PUMPING`
- thesis: `Ladder says PUMPING — buy flow and volume already aligned. This is motion, not the early heat chip.`
- trigger: `Late if you chase; watch for COOLING before adding.`
- Soften with live leads when present: append `Flow {buy:.0%} buy · vol {vol:.0%}.` to thesis (same units as K3-7b).

**COOLING (optional, demoted):**
- move: `FADING · {Name} (SN{n})`
- badge: `FADING`
- thesis: `Heat rolling off — ladder in COOLING.`
- trigger: `Don't treat as a fresh pump entry.`

**Honest-empty (0 PUMPING, ignore COOLING-only for “has alerts”):**
- Title still shows.
- Body: `No names in PUMPING right now. Early heat stays on the dossier chip when the lead is warming.`
- Never blank; never “Warming Up.”

---

## 4. Banned phrases

Inherit K3-7 `_BANNED_IN_HERO` on move/thesis/trigger:

`council scan` · `blocked:` · `audit gate` · `size in` · `wait —` · `publish` · `leads 24h`

Also banned in this lane:
- Putting **PUMPING** / `IN PLAY` on the dossier chip
- Audit/engine jargon: `composite_score`, `phase_entry`, `hysteresis`, `signal_snapshot`
- False urgency: `guaranteed`, `ape now`, `don't miss`
- Empty filler: `Warming Up`, `N/A`, `Loading…` as final empty copy

---

## 5. API shape — `GET /api/pump-alerts`

Fields only (no code):

```
status: "success" | "empty" | "unavailable" | "error"
count: int                    # PUMPING rows only (primary)
alerts: [
  {
    netuid: int
    name: str
    phase: "PUMPING" | "COOLING"
    score: float | null       # ladder composite/final
    move: str
    thesis: str
    trigger: str
    badge: str                # display: "PUMPING" | "FADING"
    buy_ratio: float | null
    volume_intensity: float | null
    updated_at: str | null
  }
]
empty_message: str            # always set when count==0
error: str | null
```

SSR may call the same builder used by the route. Contract: add path to `CONTRACT` when wired.

---

## 6. Build list (Composer)

| Action | Path |
|--------|------|
| CREATE | `internal/learning/pump_alert.py` — build rows from ladder (mirror `dpick_pump.py`) |
| CREATE | `templates/partials/premium/pump_alert.html` — section + rows + empty |
| TOUCH | `templates/partials/premium_cockpit.html` — include **between** council_stage and living_focus |
| TOUCH | `server.py` — `GET /api/pump-alerts`; pass `pump_alerts` into index SSR |
| TOUCH | `static/js/cockpit_hydrate.js` (and home_live if needed) — patch `#pump-alert-body` by ID only |
| CREATE | `internal/preview/k3_pump_alert.py` + `templates/preview/k3_pump_alert.html` |
| TOUCH | `server.py` — `GET /preview/k3-pump-alert` (fixture with ≥1 PUMPING row @390px) |
| CREATE | `tests/test_pump_alert.py` — phase filter, empty copy, banned substrings, PUMPING≠dossier |
| TOUCH | `tests/test_endpoint_contract.py` — add `/api/pump-alerts` (+ preview if other previews are listed) |

Do **not** change `dpick_pump.py` display phases (PUMPING stays hidden on chip).

---

## 7. Out of scope

- Telegram / push / `CONVICTION_ALERTS_ENABLED`
- Wiring alerts into council pick / shortlist / Daily Call
- Session (Now/hour) chip changes
- New ladder thresholds or scheduler work
- Pro-cockpit SimiVision panel duplication

---

## AC

- [ ] Homepage shows `#section-pump-alert` below dossier, above Living Focus
- [ ] PUMPING never appears on `#k3-pump-chip`
- [ ] Rows show move / thesis / trigger / badge; empty state uses locked copy
- [ ] `GET /api/pump-alerts` returns locked JSON shape; contract green
- [ ] `/preview/k3-pump-alert` renders fixture PUMPING row at 390px
- [ ] Banned substrings absent from move/thesis/trigger

## RISKS / NON-GOALS

- Risk: hydrate overwriting dossier — patch alert host only  
- Non-goal: real-time push; council coupling

## ESCALATE_HIGH?: no

---

## PASS/FAIL self-check

| Check | Result |
|-------|--------|
| Separate from dossier (PUMPING off chip) | PASS |
| Placement vs Living Focus explicit | PASS |
| Trader copy + honest-empty | PASS |
| K3-7 ban list inherited | PASS |
| Minimal API fields only | PASS |
| Build list mirrors dpick_pump pattern | PASS |
| Out of scope named | PASS |
| Tight enough for Composer without inventing product | PASS |

**SELF-CHECK: PASS**
