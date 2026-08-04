# Tribunal hero v3 — Visual Lock (implementation spec)

**Status:** SUPERSEDED by Council Hero v4 (2026-08-04 Ditto) — see `docs/council-hero-cursor-handoff.md`
**Inputs:** `docs/design/tribunal-hero-v3-reference.png`,
`docs/design/tribunal-hero-decisions.md`
**Branch:** `cursor/tribunal-hero-visual-lock-4c3f` (PR #794)
**#788:** reference-only for `verdict_kind` + preserved IDs — **not** layout/CSS

> **Authority:** `tribunal-hero-decisions.md` + this doc override the reference
> PNG where they conflict. The PNG is mood/composition only — do not
> pixel-match hardcoded values, seat count, or placeholder metrics from the
> render.

---

## Known reference-vs-decisions deltas

**Authority:** `tribunal-hero-decisions.md` + this section override the reference
PNG where they conflict. The PNG is **mood/composition** — not a pixel spec.
Do not "fix" implementation to match placeholder art that violates locked rules.

| # | Topic | What the PNG shows | What to implement | Notes |
|---|--------|-------------------|-------------------|-------|
| **1** | **Judge weight display** | Mixed units: Oracle `0.33`, Echo `0.62` (decimals), Pulse `54%` (percent). Values do **not** sum to 1.0. | **Canonical format: percent only**, from `stats.judge_weights`: `Math.round(weight * 100) + '%'`. All three normalized 0–1, sum = 1.0 on live API. | PNG numbers are **placeholder art**, not literal targets. Equal thirds (~33%) is expected on prod today. Never mix decimal and percent formats on the same layout. |
| **2** | **Center verdict label** | `SEALED · BUY` | `SEALED · LONG` (and `GATED · HOLD`, etc.) | `verdictKind()` normalizes `BUY → LONG` before building the label (decisions §3). PNG predates that rule. **Slice 2 AC: `SEALED · LONG`, not `SEALED · BUY`.** Do not match the screenshot back to `BUY`. |
| **3** | **Ring fill** | Two-tone arc (bright top-right, dim remainder) | Conviction % drives arc fill via `stroke-dashoffset` or equivalent | **No gap** — PNG matches §4.1 ring-fill concept. |
| **4** | **Waveform / power strokes** | Flowing continuous strokes; visually **not** three independent radial spokes. Reads as one shared path system (oracle down into top node; echo/pulse flow may share continuity behind/near the ring). | **One shared overlay SVG** (`tribunal-hero__wiring`) spanning the hero — see architecture lock below. **Not** three per-seat `<svg data-waveform>` elements. | **Resolve before Slice 3.** File structure change, not just CSS. |
| **5** | **LAST 5 tick strips** | Amber bars varying height/opacity | Hit = tall bright amber; miss = short dim bronze (decisions §4) | **No gap** on closer look — PNG matches spec. |
| **6** | **Metrics Row 3** | Fully rendered "Market Alignment" with `81% SIGNAL SCORE` | **Omit in v1** — `data-metric="alignment"` stays `hidden` or absent from DOM | PNG shows **future-state** design. Decisions §6/§9: phase 2 only. **Do not "fix" to match screenshot** by adding Row 3 in v1. |

Also applies from earlier comps (not in current 3-judge PNG but still locked):
- **Seat count:** exactly **3 judges** (`oracle`, `echo`, `pulse`) — never 4 experts on the ring.
- **Ring %:** live from `/api/daily-pick`, not hardcoded `71%` on hydrate (fixture `0.71` OK for sealed preview only).
- **Rows 1–2 metrics:** no placeholder `68.7%` / `60.0%` — honest-empty or real API only.

### Delta 4 — Wiring SVG architecture (LOCKED before Slice 3)

**Chosen:** one shared `<svg class="tribunal-hero__wiring">` with named paths in a
single `viewBox` — **not** three isolated per-seat waveform SVGs.

| Approach | Verdict |
|----------|---------|
| Three `<svg class="tribunal-hero__waveform">` per judge seat | **Rejected** — breaks at 390px; contradicts reference continuity; reads as connector + wave. |
| One hero-spanning wiring SVG with named `<path>` elements | **LOCKED** — matches reference's shared path system. |

**Path count:** the reference may read as **two** flowing strokes (oracle → top
node; echo ↔ pulse continuity through lower ring) rather than three radial
spokes. v1 may implement **2–3 named paths** inside the **same** wiring SVG —
geometry should follow the reference's flowing continuity, not three identical
radial lines. Minimum: oracle path to top entry node; echo + pulse paths to
lower entry nodes, all in one coordinate space.

```html
<section class="tribunal-hero" id="tribunal-hero">
  <svg class="tribunal-hero__wiring" viewBox="0 0 390 520" aria-hidden="true">
    <circle class="tribunal-hero__ring-track" … />
    <path class="tribunal-hero__ring-fill" … />
    <path class="tribunal-hero__power tribunal-hero__power--oracle" … />
    <path class="tribunal-hero__power tribunal-hero__power--echo" … />
    <path class="tribunal-hero__power tribunal-hero__power--pulse" … />
    <!-- entry-node circles where paths meet the ring -->
  </svg>
  <div class="tribunal-hero__ring-center">…</div>
  <article class="tribunal-hero__judge" data-judge="oracle">…label, weight%, LAST 5…</article>
  …
</section>
```

**Rules:**
- Judge seat HTML holds **label, weight %, LAST 5 ticks only** — no power SVG.
- Optional seat sparkline (texture) is decorative only; not the ring power path.
- Paths are **static v1** markup — not API-driven.
- Ring fill: JS updates `.tribunal-hero__ring-fill` dash offset from conviction %.
- `prefers-reduced-motion`: static wiring, no animation.

**Slice 3 gate:** wiring SVG merged before seat polish. AC = paths terminate on
ring + three weight %s hydrated — not pixel-perfect path count if 2-path layout
matches reference better than 3 radial spokes.

---

## 1. Scope

| In scope | Out of scope |
|----------|--------------|
| New tribunal hero on `/preview/tribunal?state=` | Live wire into `council_stage.html` |
| 3 judge seats + ring + monument T + metrics panel | Rescoring, new pick logic |
| Hydrate from existing APIs | Tribunal PR #788 spectrum markup |
| Amber tick strips when `judge_last5` exists | Market Alignment row (phase 2) |
| Four verdict states (sealed/gated/forming/cold) | Cosmetic churn outside hero |

---

## 2. File map

| Component | File | Notes |
|-----------|------|-------|
| Preview route | `server.py` | `GET /preview/tribunal` — follow `preview/k3_hold` pattern |
| Preview context builder | `internal/preview/tribunal_hero.py` | Fixture payloads per `?state=`; optional live API merge |
| Preview shell | `templates/preview/tribunal.html` | Minimal layout, `data-hydrate="0"` for SSR sign-off |
| Hero partial | `templates/partials/premium/tribunal_hero.html` | **New** — do not reuse #788 `tribunal.html` spectrum |
| Styles | `static/css/ui.css` | `.tribunal-hero*` block — mist/pewter/amber tokens only |
| Hydrate | `static/js/cockpit_hydrate.js` | `renderTribunalHero()`, `patchTribunalFromDailyPick()`, `patchTribunalJudges()` |
| Contract | `tests/test_endpoint_contract.py` | Add `GET /preview/tribunal` |

**Do not touch** `templates/partials/premium/council_stage.html` in this slice.

**Parallel (separate PR):** `handoffs/council-judge-weights-to-claude.md` —
`patchK3JudgeWeights()` on `#k3-layer-council` for the *existing* K3 dossier.

---

## 3. DOM structure (tribunal_hero.html)

```html
<section class="tribunal-hero" id="tribunal-hero" data-verdict-kind="{{ verdict_kind }}">
  <header class="tribunal-hero__brand">THE TRIBUNAL</header>

  <!-- Wiring layer: ring + 3 power paths (see Decisions deltas §4) -->
  <svg class="tribunal-hero__wiring" viewBox="0 0 390 520" aria-hidden="true">
    …ring track, fill arc, 3 power paths, entry nodes…
  </svg>
  <div class="tribunal-hero__ring-center">
    <span id="k3-orb-score" class="tribunal-hero__pct">—</span>
    <span class="tribunal-hero__pct-label">VERDICT CONFIDENCE</span>
    <span id="k3-action-badge" class="tribunal-hero__verdict-label">…</span>
  </div>

  <!-- Monument T (decorative) -->
  <div class="tribunal-hero__monument" aria-hidden="true">…</div>

  <!-- 3 judge seats -->
  <article class="tribunal-hero__judge tribunal-hero__judge--oracle" data-judge="oracle">
    <h3 class="tribunal-hero__judge-name">ORACLE</h3>
    <span class="tribunal-hero__judge-weight" data-judge-weight>—</span>
    <!-- optional decorative sparkline only — power path lives in __wiring SVG -->
    <div class="tribunal-hero__last5" data-last5 hidden>…5 ticks…</div>
  </article>
  <!-- echo: lower-left, pulse: lower-right — same pattern -->

  <!-- Headline (sr / hydrate) -->
  <p id="k3-call-headline" class="tribunal-hero__sr-only">…</p>

  <!-- Metrics panel -->
  <footer class="tribunal-hero__metrics">
    <div class="tribunal-hero__metric" data-metric="accuracy">…</div>
    <div class="tribunal-hero__metric" data-metric="recent">…</div>
    <div class="tribunal-hero__metric" data-metric="alignment" hidden>…phase 2…</div>
  </footer>
</section>
```

**Preserved IDs** (for future live wire): `#k3-orb-score`, `#k3-action-badge`,
`#k3-call-headline`.

---

## 4. Data wiring

### 4.1 Ring conviction — `GET /api/daily-pick`

```js
var active = payload.pick || payload.candidate;
var raw = active && (
  active.final_confidence != null ? active.final_confidence :
  active.confidence != null ? active.confidence :
  active.conviction
);
// 0–1 → pct; null → no number, ring empty track only
```

### 4.2 Verdict kind + center label

```js
function verdictKind(payload) { /* see tribunal-hero-decisions.md */ }
```

| kind | `#k3-action-badge` | ring fill |
|------|-------------------|-----------|
| sealed | `SEALED · LONG` | conviction % |
| gated | `GATED · HOLD` | conviction % (candidate) |
| forming | `FORMING` | no % |
| cold | `COLD` | no % |

### 4.3 Three judge seats — `GET /api/learning/stats`

```json
"data": {
  "judge_weights": { "oracle": 0.333, "echo": 0.333, "pulse": 0.333 },
  "judge_last5": {
    "oracle": [true, true, null, true, false],
    "echo": [true, false, true, true, false],
    "pulse": [null, true, true, true, true]
  }
}
```

- Weight display: `Math.round(weight * 100) + '%'` for all three judges (see
  deltas §1 — never mix decimal and percent formats)
- **`judge_last5` may be absent** until backend PR lands → hide
  `.tribunal-hero__last5` (`hidden`), do not render fake ticks

### 4.4 Council recent row — same API

```json
"council_last5": [true, true, true, false, false]
```

Win rate when `trust_banner.graded > 0`:
`correct / (correct + wrong)`. When `!trust_banner.ready`, show
`trust_banner.message` (e.g. `1/30 graded`).

### 4.5 Waveforms (see Decisions deltas §4)

Power strokes live in **one** `.tribunal-hero__wiring` overlay SVG — three
`<path class="tribunal-hero__power--{oracle|echo|pulse}">` elements sharing a
single `viewBox`, each terminating on a ring entry node. **Not** per-seat SVGs.

Seat cards may include an optional decorative sparkline (texture); it is not
the power path. v1 paths are static markup, not API-driven.

### 4.6 LAST 5 tick strip

Per judge, when `judge_last5[judge]` is an array of length 5:

| Value | Render |
|-------|--------|
| `true` | tall amber tick + glow |
| `false` | short bronze tick, no glow |
| `null` | empty slot (dim dash or gap) |

Oldest = index 0, newest = index 4. Caption: `LAST 5` muted gold.

---

## 5. Preview fixtures (`?state=`)

| Query | Fixture intent |
|-------|----------------|
| `sealed` | `action: LONG`, `pick` populated, conviction ~0.71, all judges ~0.33 |
| `gated` | `action: HOLD`, `pick: null`, `candidate` populated, ~0.34 — **matches prod today** |
| `forming` | `status: pending`, no pick/candidate |
| `cold` | `status: timeout`, empty |

Default: `gated` (honest prod shape). SSR must render without hydrate;
hydrate upgrades from live APIs when enabled on home only.

---

## 6. Implementation slices (order)

### Slice 1 — Skeleton + preview route
- [ ] `tribunal_hero.html` static SSR with gated fixture
- [ ] `/preview/tribunal?state=gated` returns 200
- [ ] Contract test entry
- **Screenshot AC:** layout matches reference at 390px — ring, T, 3 seats, panel

### Slice 2 — Ring + verdict label
- [ ] Ring arc from conviction %; `verdictKind()` drives badge text
- [ ] All four `?state=` fixtures render distinct center labels
- **Screenshot AC:** sealed shows `SEALED · LONG` + 71% (not `SEALED · BUY`);
  gated shows `GATED · HOLD`; forming/cold show no fake %

### Slice 3 — Judge seats + weights + wiring SVG
- [ ] **Gate:** `.tribunal-hero__wiring` exists with ring + 3 power paths (Decisions deltas §4)
- [ ] Hydrate `judge_weights` into three HTML seats
- [ ] Ring fill tracks conviction % on wiring arc
- **Screenshot AC:** three weights visible; no fourth seat; three paths visibly terminate on ring; no separate connector lines

### Slice 4 — LAST 5 ticks
- [ ] Render ticks when `judge_last5` present; hidden when absent
- [ ] Council row ticks from `council_last5`
- **Screenshot AC:** with fixture data, ticks match reference; without API field, strips absent (not fake)

### Slice 5 — Metrics panel
- [ ] Row 1: accuracy when `trust_banner.ready`, else message
- [ ] Row 2: win rate + council_last5 when graded > 0
- [ ] Row 3: **remain hidden** — do not add to match PNG (deltas §6)
- **Screenshot AC:** prod-shaped gated state shows sample message not fake 68.7%;
  only two metric rows visible

### Slice 6 — Polish pass
- [ ] 390px `g0_phone_qa.sh` still PASS on `/` (preview is separate)
- [ ] `prefers-reduced-motion`: static ring, no pulse animation
- **Human AC:** VISUAL GO on sealed + gated screenshots

---

## 7. CSS tokens (use existing — no new palette)

From `ui.css` mist/pewter wave: `--accent-amber`, `--text-primary`,
`--surface-glass`, `--ring-track`, glow via `box-shadow` / `filter`.
Reference hex ~`#FFB800` range for hits; bronze `#6B5A45` for miss ticks.

---

## 8. Hydrate entry points

Preview page: optional small inline script or reuse `cockpit_hydrate.js` with
`window.__TRIBUNAL_PREVIEW = true` guard — only fetch:
- `/api/daily-pick`
- `/api/learning/stats`

Do **not** run full home tier-batch on preview.

```js
// New exports (or namespace on window.HomeLiveRefresh)
renderTribunalHero(dailyPick, learningStats);
```

---

## 9. Tests

| Test | Assert |
|------|--------|
| `test_endpoint_contract.py` | `GET /preview/tribunal` → non-5xx |
| `test_tribunal_hero_preview.py` (new, small) | gated fixture contains `tribunal-hero`, three `data-judge`, no fake 71% when forming |

---

## 10. Live wire gate (post-VISUAL GO — separate PR)

Only after human comments **VISUAL GO** on sealed + gated preview screenshots:

1. Include `tribunal_hero.html` from `council_stage.html` replacing `#k3-layer-claim` claim orb block — **or** swap entire claim layer per lock review
2. Enable hydrate path on home `renderDailyPick` → `renderTribunalHero`
3. Re-run 390px sign-off pack

---

LOCK_PATH: handoffs/tribunal-hero-visual-lock.md
DEPENDS_ON: `judge_last5` / `council_last5` backend (parallel PR)
REFERENCE: docs/design/tribunal-hero-v3-reference.png
