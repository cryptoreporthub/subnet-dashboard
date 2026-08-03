# Tribunal hero v3 — visual decisions

**Status:** DRAFT — awaiting CONFIRM lines below
**Canonical reference:** `docs/design/tribunal-hero-v3-reference.png`
**Canonical choice:** **Option A** — this PNG is the design target. PR #788
(`cursor/tribunal-hero-redesign-192d`, `tribunal.html` spectrum layout) is
**reference only** for verdict-state logic and preserved DOM IDs — its
markup/CSS is **not** the layout spec.

---

## 1. Ring % source

**Decision:** ring fill = `active.final_confidence` where
`active = payload.pick || payload.candidate` from `GET /api/daily-pick`.
Falls back to `active.confidence` then `active.conviction` if
`final_confidence` is null (matches existing `patchK3DossierFromPayload`
priority chain — do not diverge).

- 0–1 float → `%` = `round(value * 100)`
- `null` → ring shows **no** fake number; conf_state = `resolving` (existing
  three-state pattern — do not regress)

## 2. Four council seats — CONFIRM

The mockup labels are: `QUANT 2.0`, `DARK HORSE 1.0`, `TECHNICAL 0.8`,
`PULSE 54%`.

**Problem:** three of those (`quant`, `dark_horse`, `technical`) are
**expert** names (`stats.expert_weights` on `/api/learning/stats`) and one
(`pulse`) is a **judge** name (`stats.judge_weights`, alongside `oracle` and
`echo`). These are two different soul-map families with different scales:

| Family | Keys | Scale | Source |
|--------|------|-------|--------|
| Experts | `quant`, `hype`, `dark_horse`, `technical` | raw weight, baseline 1.0 (can exceed) | `stats.expert_weights` |
| Judges | `oracle`, `echo`, `pulse` | normalized 0–1, sum = 1.0 | `stats.judge_weights` |

**CONFIRM — pick one:**

- [ ] **(a)** Four seats = the four **experts** (`quant`, `hype`, `dark_horse`,
      `technical`). Drop `pulse` from the mockup; use `hype` for the fourth
      seat instead. Consistent family, consistent scale.
- [ ] **(b)** Four seats = **mixed** as drawn (`quant`, `dark_horse`,
      `technical` experts + `pulse` judge). Requires two different value
      formats on one ring (raw weight vs 0–1 normalized) — visually
      inconsistent unless value display is normalized to a common 0–100
      display scale for all four regardless of source family.
- [ ] **(c)** Three council seats = **judges** (`oracle`, `echo`, `pulse`)
      + a separate single "Expert lean" readout elsewhere (not on the ring).
      Matches the original ask ("Oracle/Echo/Pulse ring") from the judge
      wire slice — but changes the mockup's 4-seat layout to 3.

**Recommendation:** (a) — keeps one data family per ring, avoids a
mixed-scale display bug, and reuses the existing `CANONICAL_EXPERTS` order
already in `cockpit_hydrate.js`.

## 3. Center label (SEALED · BUY / GATED · HOLD)

**Decision:** derive `verdict_kind` client-side (no `tribunal` key exists on
`/api/daily-pick` today):

```js
function verdictKind(payload) {
  var act = String(payload.action || 'HOLD').toUpperCase();
  if (act === 'BUY') act = 'LONG';
  if (payload.pick && act === 'LONG') return 'sealed';
  if (!payload.pick && payload.candidate && act === 'HOLD') return 'gated';
  if (String(payload.status || '').toLowerCase() === 'pending') return 'forming';
  return 'cold';
}
```

| kind | center label |
|------|---------------|
| sealed | `SEALED · {ACTION}` (LONG/SHORT) |
| gated | `GATED · HOLD` |
| forming | `FORMING` (no %, no name) |
| cold | `COLD` (timeout/error) |

Prod today is **gated** — do not hardcode `SEALED` as the only state; build
and screenshot all four on `/preview/tribunal` before wiring live.

## 4. Metrics panel rows — CONFIRM mapping

Mockup shows three rows. Proposed mapping to real fields
(`/api/learning/stats`):

| Row | Mockup | Proposed source | Confirm? |
|-----|--------|------------------|----------|
| 1 | Historical accuracy — 68.7% | `stats.trust_banner.accuracy` (only when `trust_banner.ready === true`, else honest-empty per existing RF-2 rule) | [ ] OK |
| 2 | Recent verdicts — 60.0% win rate + 5 ticks | `stats.trust_banner.streak.council` for the whisper text; **the 5-tick strip itself has no data source yet** — see §5 below | [ ] needs new field |
| 3 | Market alignment — 81% signal score | No existing single field maps to "council consensus score." Closest real candidate: `judges` `consensus.score` from `/api/judges?netuid=N` for the *active* pick's subnet — but that's per-subnet, not council-wide. **CONFIRM what this row means** or mark phase-2/defer. | [ ] needs definition |

**Do not invent numbers for rows 2–3 if no real field exists — honest-empty
placeholder until backend field is confirmed, same rule as rest of the app
(RF-2).**

## 5. "LAST 5" tick strip — real gap, needs backend field or reduced scope

**Confirmed by code read (`internal/learning/streaks.py`,
`tests/test_streaks_and_judge_audit.py`):**

- `compute_streaks()` returns a **streak length** per expert (e.g.
  `{"length": 4, "active": true, "label": "Quant · 4 in a row"}`), **not**
  a fixed 5-slot hit/miss array.
- There is **no existing endpoint** that returns "last 5 resolved
  predictions, in order, per expert/judge" as booleans.
- The underlying data (`resolved` predictions with `correct: bool` and
  `expert`/`resolved_at`) exists in `predictions_store.load_predictions()`
  — the ticks are derivable, just not exposed yet.

**CONFIRM — pick one:**

- [ ] **(a)** New backend field: add `last5` (array of 5 booleans,
      oldest→newest, pad with `null` if <5 resolved) per expert (and
      per judge if seats include judges) on `/api/learning/stats` or
      `/api/learning-metrics`. Small, additive, ponytail-sized change to
      `internal/learning/streaks.py` + `routes.py`. **Recommended** —
      keeps ticks honest instead of decorative.
- [ ] **(b)** Ship v1 with the tick strip showing the **existing** streak
      length only (e.g. render `min(length, 5)` filled ticks, rest dim) —
      no new backend field, but loses the oldest→newest hit/miss detail
      the mockup implies.
- [ ] **(c)** Defer the tick strip to phase 2; ship ring + waveforms +
      center label first, ticks come once (a) lands.

**Recommendation:** (a) for correctness, but it's the one item in this
whole slice that touches `internal/learning/streaks.py` (owned by Agent A
per the ownership matrix) — flag for a tiny follow-up PR, not bundled into
the frontend-only visual slice.

## 6. Waveform-per-seat data source

Each seat's background waveform (Quant's smooth curve, Dark Horse's EKG,
Technical's jagged line, Pulse's plasma wave) is **decorative only** in v1
— no real per-tick price/score series is wired. **CONFIRM:** ship as a
static/generated decorative sparkline (no data claim), or defer entirely
until a real signal-history series exists. Do not label it with units that
imply live data if it isn't.

## 7. Monument "T"

**Decision:** ship in v1 — purely decorative (brand mark), no data binding,
no AC risk. Static asset/CSS, does not block phase-1 wire correctness.

## 8. Out of scope (this slice)

- Mist/pewter shell, thumb dock, sections below hero — untouched
- Live wire into `council_stage.html` — **preview route only** until
  human VISUAL GO per state (sealed/gated/forming/cold)
- `internal/learning/routes.py` beyond the additive `last5` field (if §5a
  is chosen) — no rescoring, no new weight logic
- Tribunal PR #788 markup — not reused as layout; verdict-state logic and
  preserved hydrate IDs (`#k3-orb-score`, `#k3-action-badge`,
  `#k3-call-headline`) may be reused

## 9. Definition of done (per verdict state)

- [ ] Screenshot of `/preview/tribunal?state={sealed|gated|forming|cold}`
      matches `docs/design/tribunal-hero-v3-reference.png` for that state
- [ ] 390px screenshot — ring not clipped, label readable
- [ ] `scripts/g0_phone_qa.sh` PASS
- [ ] No fake conviction when `final_confidence`/`confidence` is null
- [ ] Four seats show real values from the family chosen in §2
- [ ] Metrics panel shows honest-empty for any row without a confirmed
      real field (§4)
- [ ] Human comments **VISUAL GO** on this doc or the PR, per state

---

**Next step once CONFIRM lines are answered:** hand this file + the
canonical PNG to Claude for `handoffs/tribunal-hero-visual-lock.md`
(component → file mapping + slice order). Do not skip the CONFIRM items —
they are the difference between "matches the picture" and "looks close but
data is wrong or invented."
