# K3-9 Pump Desk LOCK — Simple, graded, complete

**Status:** REVISED 2026-07-19 · Grok COPY/PRODUCT (spitball softened — do not force council)  
**Supersedes presentation of:** K3-8 / K3-8b horizontal scroll as primary UI  
**Keeps:** Lead-first phases · projected % · HIT / FAKE / MISS grades  
**North star:** Feel **whole and complete**. Presentation is the gap (~50%); backend is rich (~85%). Never rush a half-section. Never make users squint.

---

## VERDICT: PASS (direction) — with soft authority

Council/judges **own the Daily Call**. They do **not** have to own the pump desk.  
If a “who called it” layer helps, use **simple personas** — not a second scoring stack.

Human spitball → keep the juice, drop the force:
- Multi-name desk ✓  
- Projection + track record ✓  
- Pump fake grading ✓  
- Council as required authority ✗ (optional later, only if it stays obvious)

---

## 0. Completeness bar (whole product)

A section ships when it is complete from every angle we can name:

| Angle | Pump desk must answer |
|-------|------------------------|
| **What** | Which names, early vs chase vs exit |
| **Why now** | One trader sentence (flow before price) |
| **How much** | Projected % + horizon |
| **How it went** | Hit / fake / miss when resolved |
| **Trust** | Honest-empty; no fake accuracy strip |
| **Eyes** | Vertical board, large type, one job per row — no squint |

If any angle is missing, the section is **not done** — polish before adding features.

**Site-wide note:** Rich backend data should fund *spectacular simplicity* per section (dossier, lead desk, Living Focus, letter) — not more panels. Presentation debt is the real workstream after K3 Phase 1.

---

## 1. Problem → wanted

| Today | Wanted |
|-------|--------|
| Carousel of status cards | Calm **vertical board** (usually >1 name) |
| Phase = whole story | Phase + **projected move** + later **grade** |
| No memory | Desk remembers what it watched |
| Feels rushed / lagging | Feels like a finished product surface |

---

## 2. Architecture (thin)

```
Ladder (sensor)  →  Stamp call (desk)  →  Ledger  →  Grade
STIRRING / ACC   →  entry + projected% →  pump_calls.json → HIT | FAKE | MISS
PUMPING / COOL   →  status update      →  resolve at horizon
```

| Piece | Role |
|-------|------|
| Ladder + lead gate | When a name enters the desk |
| Projection | Reuse `predicted_pct` helpers **or** a simple phase→% table if council path is noisy — pick whichever is clearer in UI |
| Personas (optional) | Light attribution only — see §3 |
| SciWeave hybrid | Desk accuracy strip when sample enough — same honesty rules as trust banner |
| `data/pump_calls.json` | Thin ledger (do not collide with daily predictions) |

**Do not invent** a parallel judge council for pumps. One brain on the site is enough.

---

## 3. Optional: simple personas (not a scoring system)

If we want “someone” on the call for personality + accountability **without** Oracle/Echo/Pulse complexity:

| Persona | Vibe | When stamped |
|---------|------|--------------|
| **Alpha Chaser** | Early heat / STIRRING | Lead entry |
| **Beta Maxxer** | Building / ACCUMULATING | Lead entry |
| **Karma Chaser** | Confirmed / chase-risk watch | PUMPING update |
| **Fade Watch** | Exit / COOLING | Exit stamp |

Rules:
- Names are **labels**, not models. One persona per open call, set at stamp from phase.
- Track record per persona is a **later** polish (9d+), not required for 9a–9b.
- Ban: nested scores, 3-judge lines on every pump row, weight jargon in this lane.

---

## 4. Thresholds (unchanged spitball juice)

| Knob | Default | Meaning |
|------|---------|---------|
| Hit ratio | **0.60** | `actual ≥ 0.60 × predicted` → **HIT** |
| Fake floor | **+1.5%** | Must clear before counting a real attempt |
| Fake ceiling | **0.40 × predicted** | Cleared floor but never got to 40% of projected → **FAKE** |
| Else | | **MISS** |

Copy:
- HIT → `Hit · +X% of +Y% projected`
- FAKE → `Pump fake · peaked +X% vs +Y% projected`
- MISS → `Miss · never cleared +1.5%`

Strip (n ≥ 10): `Last N: H% hit · F% fake · M% miss`

---

## 5. Presentation

**Vertical ranked board** — 390px first, readable at arm’s length.

```
Lead desk                    Last 24: 41% hit · 28% fake
────────────────────────────────────────────────────────
BUILDING  Apex · SN99        +6% · 4h     Beta Maxxer
          Flow ahead of price — entry open

EARLY     Sub42 · SN42       +3.5% · 4h   Alpha Chaser
          Buy pressure before price runs

CONFIRMED Coldint · SN29     chase        Karma Chaser
          Live — rotate, don’t chase

FAKE      …                  peaked +1.8% vs +6%
```

- Cap **8** rows; LEAD first; graded teasers max 2 at bottom  
- One job per row; large name; % is second beat  
- No carousel; no pink audit chrome; no “Tier 3 Scanner” jargon in the title — prefer **Lead desk** or **Pump desk**

---

## 6. Slice queue

| Slice | Deliverable |
|-------|-------------|
| **K3-9a** | Ledger + stamp + resolve/grade + tests (no UI rewrite yet) |
| **K3-9b** | Vertical desk UI — presentation bar: readable, calm, complete empty states |
| **K3-9c** | Real projected % + accuracy strip |
| **K3-9d** | Optional personas + per-persona hit rate (only if still feels simple) |

Skip 9d if personas clutter. Completeness > cleverness.

---

## 7. Non-goals

- Forcing council/judges into this lane  
- A sophisticated second recommendation engine  
- Replacing Daily Call  
- Shipping presentation-incomplete “MVP chrome”

---

## VERDICT: PASS

Next: **K3-9a** ledger when human greenlights — or a **presentation audit** pass across home sections first if that is the higher priority (backend 85% / UI 50%).
