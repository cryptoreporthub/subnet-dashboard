# K3-7 Vision — Hero Copy & Information Architecture

**Owner:** K3 (design)  
**Date:** 2026-07-19  
**Status:** Vision for human sign-off → Composer builds after  
**Supersedes:** PR #360 audit-note brief; rigid formula locks

---

## Verdict in one line

**Stop narrating the audit. Start answering the trader.**  
The hero’s job is: *what do I do, with what, why this one, and what would change my mind.* Everything else is peel.

---

## 1. The opening 5 seconds

### What they see (phone, 390px)

Forget the current stack order (trust chips → orb → name → yellow WAIT box). Reorder the claim so the **decision leads** and the orb **supports**.

| Beat | ~time | Content |
|------|-------|---------|
| 0.0s | Brand whisper | `SimiVision` — already there; keep quiet, don’t compete with the call |
| 0.5s | **The call** | One verb + one subnet: `HOLD · SN99` or `LONG · Apex` — largest type on screen |
| 1.5s | **The why** | One sentence in trader English. Not process. Not gates. A reason that implies edge. |
| 3.0s | Orb + % | Conviction as *strength of the call*, not the headline. On HOLD, ring reads cool/calm (cyan), not alarm yellow. |
| 4.0s | Horizon chips | Now / 24h / 7d — same call, different lens; pin stays |
| 5.0s | **Also weighed** | One line or peek-strip: who lost and why — proof this isn’t a ranking dump |

**What they should feel**

- On a BUY day: *someone already did the work; I can act or dig deeper.*
- On today’s HOLD day: *I’m not missing a sized long — and I know the line that flips it.* Calm authority, not a blocked form.

**Kill above the fold**

- Trust / hybrid / enrichment chips as primary noise (demote below claim or into Learning peel)
- Yellow “WAIT / Blocked / audit gate” framing — it reads as system error
- Duplicate badge + brief saying the same thing twice

**Keep (shell)**

Orb, horizon chips, peel layers. Don’t rebuild the dossier — **re-rank what’s loud**.

---

## 2. Copy examples (real words, not templates)

### A. Today — HOLD + candidate (SN99 ~23%, floor 45%)

**Call**  
`HOLD · SN99`

**Why**  
`Closest long on the 24h desk — but conviction is still half a size. Price looks rich vs peers; we won’t publish a long until that gap closes.`

**Also weighed**  
`Beat SN64 on momentum; lost to SN12 on liquidity. Neither cleared the bar either.`

**Trigger** (first-class, not buried)  
`Flip to LONG when conviction ≥ 45% and valuation drag clears.`

Tone: steady, specific, slightly proud of restraint. Never “Leads council scan.” Never “Blocked: overvalued.”

---

### B. Audited BUY (example)

**Call**  
`LONG · Apex (SN…)`

**Why**  
`Judges aligned on 24h mean-reversion with room left in the move. Liquidity can take size; risk flags are quiet.`

**Also weighed**  
`Passed SN77 — hotter tape, thinner book. We sized the one we can actually exit.`

**Accountability whisper** (small, under call)  
`Resolves in 18h · graded in public`

Tone: decisive, concrete, no victory lap. The grade later is the flex.

---

### C. Empty HOLD (no candidate)

**Call**  
`HOLD · no long`

**Why**  
`Nothing on the shortlist clears conviction and risk together. Sitting out is the call.`

**Also weighed**  
`Three names reviewed — all failed liquidity or valuation. Details in Deliberation.`

---

### Voice rules (principles, not a formula)

1. **Trader first.** If it sounds like a CI log, rewrite.
2. **Name the edge.** Why *this* vs *that*, *now* — comparison is the product.
3. **Name the flip.** Especially on HOLD. A trigger makes restraint useful.
4. **No internal nouns in the hero.** Ban from user-facing claim copy: *audit gate, publish, council scan, blocked, floor %* as drama. Numbers can appear calmly inside the trigger.
5. **Verbs that match the job:** HOLD / LONG / REDUCE — not WAIT / SIZE IN / WATCH as moralizing labels. “Watch” is fine inside Deliberation, not as the hero verb when we already have a named candidate.

---

## 3. How deliberation / alternatives should read

Deliberation is not a horizontal sticker pack of runners-up. It is **the courtroom transcript of the near-misses**.

**Above the fold (peek):** one sentence — the VS line from §2. That is enough for 80% of opens.

**Inside the Deliberation peel:** 2–4 rows, each with:

- Name + conviction %
- One clause: *why it lost* (or *why it almost won*)
- Stance chip only if it differs from the hero call

Example rows:

> **SN64 · 19%** — Stronger short-term pulse; lost on valuation.  
> **SN12 · 21%** — Cleaner book; weaker 24h momentum.  
> **SN77 · 17%** — Crowd favorite; we won’t chase thin exits.

If shortlist is empty: honest empty — `No alternatives scored today` — not “warming up.”

**Do not** make cards the interaction model for the hero. Cards belong inside the peel for scanning alternatives.

---

## 4. What makes this unmistakably SimiVision

| Competitor | They give you | We give you |
|------------|---------------|-------------|
| TaoStats / Radar / AlphaGap | Rankings, charts, scanners | **A published decision with a trigger and a grade** |
| Anyone with “AI picks” | Opaque score | **Visible near-misses + public report card** |
| Alert bots | Noise | **Deliberate silence on HOLD days that still answers “am I missing something?”** |

Moat sentence:  
**We are the only subnet surface that will tell you not to buy — show you who almost made it — and let you watch whether we were right.**

That is trailblazing presentation: decision theater with receipts, not another spreadsheet with neon.

---

## 5. Bold ideas (optional, high leverage)

### Bold A — Trigger as UI (recommended)

Under the orb on HOLD+candidate, show a **gap meter**:

`23% ──────●──────── 45%`  
`Need +22 pts · valuation still heavy`

This makes HOLD days worth reopening. Competitors can’t copy it without a real confidence floor and audit. Layout shift: small; shell stays.

### Bold B — Claim over orb (IA swap)

Put **Call + Why** above the orb; orb becomes the confidence glyph under the thesis. Today the orb is a beautiful distraction that delays the answer. One composition: verb → subnet → sentence → ring. Stats (price Δ, band) tuck under or into Evidence.

If we only ship one layout change, ship this.

---

## 6. What Composer builds first (priority)

1. **Rewrite `dpick_copy.py` voice** — HOLD+candidate and BUY examples above as target output shapes. Fields can stay `move` / `thesis` / `vs` (+ add `trigger` string). Kill audit-note phrasing in hydrate too (`cockpit_hydrate.js`).
2. **Hero IA reorder in `council_stage.html`** — Call + Why (+ trigger) lead; demote trust/enrichment chips; cool HOLD styling (not yellow alarm).
3. **VS / Also weighed always on claim** when shortlist exists — one line above the fold; Deliberation peel gets the fuller near-miss rows (copy, not just role chips).
4. **Trigger line** wired from conviction gap + top concern (Bold A lite: text first; meter if cheap).
5. **Tests** — `test_dpick_copy.py` asserts trader language samples (no “council scan” / “Blocked:” / “audit gate” in `move`/`thesis`).
6. **Preview** — refresh `/preview/k3-hold` to match today’s SN99 story for phone sign-off.

**Out of scope for this slice:** full dossier rebuild, new peel taxonomy, desktop cockpit, voice app.

---

## Sign-off ask

Approve this vision (or mark edits). Composer implements only what is signed here — no inventing a second brief.
