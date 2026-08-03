# Tribunal hero v3 — visual decisions

**Status:** LOCKED (2026-08-03, revised — 3 judges)
**Canonical reference:** `docs/design/tribunal-hero-v3-reference.png`
**Alt reference (3-judge layout study):** `docs/design/tribunal-hero-3-judge-preview.png`
**Canonical choice:** **Option A** — this PNG is the design target. PR #788
(`cursor/tribunal-hero-redesign-192d`) is reference-only for verdict-state
logic and preserved DOM IDs — not the layout spec.

---

## Locked decisions

### 1. Three council seats → **three judges**

| Position | Key | Label | Data source |
|----------|-----|-------|-------------|
| Top (above ring) | `oracle` | ORACLE | `stats.judge_weights.oracle` |
| Lower-left | `echo` | ECHO | `stats.judge_weights.echo` |
| Lower-right | `pulse` | PULSE | `stats.judge_weights.pulse` |

Values are normalized 0–1 (sum = 1.0). Display as percent:
`round(weight * 100)` → e.g. `0.333` → `33%`.

Layout: **3-fold symmetry** — oracle top-center, echo bottom-left, pulse
bottom-right. Three ring entry nodes (top, lower-left, lower-right). No
fourth quadrant.

Experts (`quant`, `hype`, `dark_horse`, `technical`) stay on
`#section-council` via `stats.expert_weights` — not on this hero ring.

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

### 4. "LAST 5" tick strips → **backend field first**

Add `last5: (boolean|null)[]` (length 5, oldest→newest, pad `null` if
<5 resolved) per **judge** (`oracle`, `echo`, `pulse`) on
`/api/learning/stats` or `/api/learning-metrics`.

Source: resolved predictions filtered by judge attribution at creation
(`judge_scores_at_creation` on prediction rows — see
`internal/council/resolver.py` / judge audit nudge path). **Agent A slice**
if expert-only filtering in `streaks.py` today — may need judge-specific
tail from resolved predictions.

Tick rendering (locked from reference PNG):
- Hit = tall bright amber tick with glow
- Miss = short dim bronze tick, no glow
- Oldest ticks slightly faded; newest brightest
- Caption: `LAST 5` in muted grey-gold

### 5. Waveform → ring power lines

Each judge seat's waveform is **one continuous stroke** from the seat into
one of three ring entry nodes. No separate connector lines. Waveforms are
**decorative in v1** (static/CSS or generated SVG per judge personality:
oracle = smooth authority, echo = rippling, pulse = sharp energy).

### 6. Bottom metrics panel

| Row | Label | Source | Notes |
|-----|-------|--------|-------|
| 1 | Historical Accuracy | `trust_banner.accuracy` when `ready === true`; else `trust_banner.message` | Pre-ready = graded sample progress, not win rate |
| 2 | Recent Verdicts | Council-wide `last5` booleans + win rate when `graded > 0` | Same backend work as §4 |
| 3 | Market Alignment | **Phase 2 — honest-empty in v1** | |

### 7. Monument T

Ship in v1 — decorative brand mark, no data binding.

### 8. Page coherence (no duplication)

```
Hero ring     → 3 judges     stats.judge_weights
Bench section → 4 experts    stats.expert_weights   (#section-council)
Today's call  → subnet + conviction   /api/daily-pick
```

### 9. Out of scope

- Mist/pewter shell, thumb dock, sections below hero
- Live wire into `council_stage.html` until human VISUAL GO per state
- PR #788 spectrum layout reuse
- Row 3 market alignment (phase 2)

### 10. Definition of done

- [ ] `/preview/tribunal?state={sealed,gated,forming,cold}` screenshots match reference
- [ ] 390px readable
- [ ] `g0_phone_qa.sh` PASS
- [ ] No fake conviction when confidence null
- [ ] Three judge seats show real `judge_weights` (oracle, echo, pulse)
- [ ] Ticks honest from `last5` backend field (or hidden until field lands)
- [ ] Human VISUAL GO per state

---

## Next step

Hand this file + `docs/design/tribunal-hero-v3-reference.png` to Claude for
`handoffs/tribunal-hero-visual-lock.md`.

Parallel track: Agent A adds `last5` per judge on `/api/learning/stats`.
