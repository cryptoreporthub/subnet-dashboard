# K3-7 Hero Copy & IA — Grok LOCK

**Date:** 2026-07-19  
**Status:** PASS (Grok slow+high)  
**Supersedes:** Composer draft in PR #360 (action brief) — subpar per user sign-off  
**Build:** Composer 2.5-fast after human OK

## Scope

Hero IA + copy for HOLD+candidate and audited BUY/SELL inside existing K3 dossier (orb, horizon chips, peel layers). Rewrite `brief.move` / `brief.thesis` / `brief.vs` + claim-layer order. Mobile 390px first viewport.

## Out of scope

New layout/shell, new APIs, deliberation card redesign beyond copy, trust-banner rewrite, whale desk, desktop cockpit, brand/theme overhaul.

## Information hierarchy (top → bottom)

1. SimiVision brand (keep; small)
2. **ACTION + subnet name** (same visual beat — `BUY Affine` / `WATCH BitMind`)
3. One **WHY** line (≤18 words; trader language)
4. One **VS** line (why this beat #2 — or why #2 almost won)
5. Orb % + horizon chips (supporting, not the story)
6. Single CTA: Pin watch / Open peel — never a second thesis
7. Peel layers = proof (Evidence → Deliberation → Council → Outcome → Learning)

## Copy framework

- Formula: `{VERB} · {Name}` + `{edge in plain English}` + `vs {runner}: {one discriminating fact}`
- VERB map: audited LONG→**BUY** · SHORT→**SELL** · HOLD+candidate→**WATCH** · empty→**NO CALL**
- Ban in UI: council scan, audit gate, publish, blocked, leads X%, need N%
- Gate math lives in peel Evidence only, as “Conviction floor 45% — now 23%”
- HOLD value = watchlist edge: name the trigger that would flip WATCH→BUY

### Example A — HOLD+candidate

```
WATCH · Affine
Best 24h lean — still too rich vs peers to size.
vs SN64: stronger flow, worse valuation.
Trigger (muted): Pin until valuation cools or conviction ≥45%.
```

### Example B — audited BUY

```
BUY · BitMind
Cleanest risk/reward this window — judges aligned.
vs SN12: higher score, thinner book.
(No trigger line; CTA = Pin + Resolves in Xh)
```

## Differentiator

TaoStats/Radar show rankings; we tell you the **move**, the **runner-up we passed**, and the **public grade when the clock ends**.

## Deliberation cards (≤12 words each)

- Header: “We weighed these — why not #1”
- Card: `{Name} · {one discriminator}` e.g. “SN64 · better flow, richer price”
- Stance chip = BUY/WATCH/SELL only (no LONG/SHORT jargon)
- Empty: “No alternatives scored this window — honest empty.”

## Anti-patterns

- Meta slogans (“Your move, not another subnet list”) as H1
- Audit-log thesis (“Leads… need 45%… Blocked: …”)
- Yellow WAIT brick that reads like an error
- Fake BUY on HOLD days
- Stacking trust/hybrid/band chips above the move
- Vs-line that only repeats % without a reason
- Copy that could sit on any subnet list unchanged

## Acceptance criteria

- [ ] 5s test @390px: stranger names VERB + subnet without scrolling
- [ ] HOLD day never shows BUY; WATCH + trigger still feels useful
- [ ] Zero user-facing strings: “council scan”, “audit gate”, “publish”, “Blocked:”
- [ ] Thesis ≤18 words; vs ≤14 words; move ≤6 words
- [ ] Deliberation cards each ≤12 words and answer “why not this”
- [ ] Audited BUY example uses clean thesis (no floor math in hero)
- [ ] Honest-empty when no candidate/shortlist (no filler confidence)
- [ ] SSR + hydrate produce identical brief strings; `test_dpick_copy` asserts both examples

## Composer files

- `internal/learning/dpick_copy.py`
- `templates/partials/premium/council_stage.html`
- `static/js/cockpit_hydrate.js`
- `tests/test_dpick_copy.py`
- `templates/preview/k3_hold.html` (fixtures)
