# Tribunal hero v3 — Visual Lock (implementation spec)

**Status:** LOCKED — implement on preview route only until human VISUAL GO
**Inputs:** `docs/design/tribunal-hero-v3-reference.png`,
`docs/design/tribunal-hero-decisions.md`
**Branch:** `cursor/tribunal-hero-visual-lock-4c3f` (PR #794)
**#788:** reference-only for `verdict_kind` + preserved IDs — **not** layout/CSS

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

  <!-- Ring -->
  <div class="tribunal-hero__ring-wrap">
    <svg class="tribunal-hero__ring" aria-hidden="true">…track + fill arc…</svg>
    <div class="tribunal-hero__ring-center">
      <span id="k3-orb-score" class="tribunal-hero__pct">—</span>
      <span class="tribunal-hero__pct-label">VERDICT CONFIDENCE</span>
      <span id="k3-action-badge" class="tribunal-hero__verdict-label">…</span>
    </div>
    <!-- 3 entry nodes: data-node="oracle|echo|pulse" -->
  </div>

  <!-- Monument T (decorative) -->
  <div class="tribunal-hero__monument" aria-hidden="true">…</div>

  <!-- 3 judge seats -->
  <article class="tribunal-hero__judge tribunal-hero__judge--oracle" data-judge="oracle">
    <h3 class="tribunal-hero__judge-name">ORACLE</h3>
    <span class="tribunal-hero__judge-weight" data-judge-weight>—</span>
    <svg class="tribunal-hero__waveform" data-waveform="oracle">…</svg>
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

- Weight display: `Math.round(weight * 100)` + `%` or fixed decimal `0.33`
- **`judge_last5` may be absent** until backend PR lands → hide
  `.tribunal-hero__last5` (`hidden`), do not render fake ticks

### 4.4 Council recent row — same API

```json
"council_last5": [true, true, true, false, false]
```

Win rate when `trust_banner.graded > 0`:
`correct / (correct + wrong)`. When `!trust_banner.ready`, show
`trust_banner.message` (e.g. `1/30 graded`).

### 4.5 Waveforms

**Decorative v1** — static inline SVG per judge personality. The waveform
stroke **must be one continuous path** from the seat into the ring entry
node (CSS or SVG — no second connector element). Classes:
`tribunal-hero__waveform--oracle|echo|pulse`.

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
- **Screenshot AC:** sealed shows `SEALED · LONG` + 71%; gated shows `GATED · HOLD`; forming/cold show no fake %

### Slice 3 — Judge seats + weights
- [ ] Hydrate `judge_weights` into three seats
- [ ] Waveform SVGs + fused stroke into ring nodes (CSS)
- **Screenshot AC:** three weights visible; no fourth seat; waveforms connect to ring

### Slice 4 — LAST 5 ticks
- [ ] Render ticks when `judge_last5` present; hidden when absent
- [ ] Council row ticks from `council_last5`
- **Screenshot AC:** with fixture data, ticks match reference; without API field, strips absent (not fake)

### Slice 5 — Metrics panel
- [ ] Row 1: accuracy when `trust_banner.ready`, else message
- [ ] Row 2: win rate + council_last5 when graded > 0
- [ ] Row 3: omitted/hidden (phase 2)
- **Screenshot AC:** prod-shaped gated state shows sample message not fake 68.7%

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
