# Tribunal hero v3 — visual decisions

**Status:** LOCKED (2026-08-03)
**Canonical reference:** `docs/design/tribunal-hero-v3-reference.png`
**Canonical choice:** **Option A** — this PNG is the design target. PR #788
(`cursor/tribunal-hero-redesign-192d`) is reference-only for verdict-state
logic and preserved DOM IDs — not the layout spec.

---

## Locked decisions

### 1. Four council seats → **four experts (a)**

| Seat | Label in mockup | Implementation key | Data source |
|------|-----------------|-------------------|-------------|
| Top-left | QUANT 2.0 | `quant` | `stats.expert_weights.quant` |
| Top-right | DARK HORSE 1.0 | `dark_horse` | `stats.expert_weights.dark_horse` |
| Bottom-left | TECHNICAL 0.8 | `technical` | `stats.expert_weights.technical` |
| Bottom-right | PULSE 54% → **HYPE** | `hype` | `stats.expert_weights.hype` |

Mockup bottom-right reads "PULSE" — implement as **HYPE** (fourth expert).
Display values normalized to a common 0–100 scale for the ring labels
(raw weight → display: `min(weight, 2.0) / 2.0 * 100` or similar; spec
in Visual Lock).

Judges (`oracle`, `echo`, `pulse`) stay on `#k3-layer-council` via
`stats.judge_weights` in the separate functional wire slice — not on
this hero ring.

### 2. Ring % source

`active.final_confidence` → `active.confidence` → `active.conviction`
where `active = payload.pick || payload.candidate` from `GET /api/daily-pick`.
Matches `patchK3DossierFromPayload` — do not diverge. `null` → resolving
state, no fake %.

### 3. Center label

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
|------|--------------|
| sealed | `SEALED · {ACTION}` |
| gated | `GATED · HOLD` |
| forming | `FORMING` |
| cold | `COLD` |

### 4. "LAST 5" tick strips → **backend field first (a)**

Add `last5: (boolean|null)[]` (length 5, oldest→newest, pad `null` if
<5 resolved) per expert on `/api/learning/stats` or `/api/learning-metrics`.
Source: `internal/learning/streaks.py` over `resolved` predictions filtered
by `expert` key. **Agent A slice** — small additive PR before or parallel
to frontend visual build.

Tick rendering (locked from reference PNG):
- Hit = tall bright amber tick with glow
- Miss = short dim bronze tick, no glow
- Oldest ticks slightly faded; newest brightest
- Caption: `LAST 5` in muted grey-gold

### 5. Waveform → ring power lines

Each seat's waveform is **one continuous stroke** from the seat into one
of four ring entry nodes. No separate connector lines. Waveforms are
**decorative in v1** (static/CSS or generated SVG) — no claim of live
signal history until a real series exists.

### 6. Bottom metrics panel

| Row | Label | Source | Notes |
|-----|-------|--------|-------|
| 1 | Historical Accuracy | `trust_banner.accuracy` when `ready === true`; else `trust_banner.message` (graded sample progress, e.g. "1/30") | Pre-ready = resolution progress, not win rate |
| 2 | Recent Verdicts | Council-wide `last5` booleans + `correct/(correct+wrong)` when `graded > 0` | Same backend work as §4 |
| 3 | Market Alignment | **Phase 2 — honest-empty in v1** | No invented consensus score |

### 7. Monument T

Ship in v1 — decorative brand mark, no data binding.

### 8. Out of scope

- Mist/pewter shell, thumb dock, sections below hero
- Live wire into `council_stage.html` until human VISUAL GO per state
- PR #788 layout reuse
- Row 3 market alignment (phase 2)

### 9. Definition of done

- [ ] `/preview/tribunal?state={sealed,gated,forming,cold}` screenshots match reference
- [ ] 390px readable
- [ ] `g0_phone_qa.sh` PASS
- [ ] No fake conviction when confidence null
- [ ] Four expert seats show real `expert_weights` (Hype not Pulse)
- [ ] Ticks honest from `last5` backend field (or hidden until field lands)
- [ ] Human VISUAL GO per state

---

## Next step

Hand this file + `docs/design/tribunal-hero-v3-reference.png` to Claude for
`handoffs/tribunal-hero-visual-lock.md`.

Parallel track: Agent A adds `last5` to learning stats API.
