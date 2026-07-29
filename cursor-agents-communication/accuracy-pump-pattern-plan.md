# Plan — Acc-0→Acc-2 call accuracy + pump pattern tracking

**Status:** ACTIVE  
**Created:** 2026-07-29  
**Baseline main:** `2ee0512` — LA #640 · LB #645 · LC/LD plan drafted · accuracy epoch reset applied on prod  
**Cadence:** One phase → one PR → merge → deploy → `./scripts/babysit_phase.sh <phase>` → human spot-check → next phase  
**Prereq:** LC + LD can run in parallel with Acc-0; Acc-1 needs Acc-0 merged; PP-1 needs PP-0 merged

---

## Executive summary

Two parallel tracks that share one substrate: **honest, time-stamped ledgers**.

| Track | Problem | Outcome |
|-------|---------|---------|
| **Acc** | Council accuracy epoch reset left `ledger.gap: true`, day picks grade at 4h but market as 24h, quant weight stuck at 2.0 after a losing book | Trustworthy grading loop + one evidence-backed accuracy experiment |
| **PP** (pump pattern) | Pump desk and council see *current phase* only — no memory of intraday waveform ("pumped 2h → dropped 1h → pumped 45m") | Segment ledger → pattern classes → spotting on pump desk + council context |

**Do not wait for Aug 4 soak** for Acc-0 or PP-0 — both are plumbing/measurement, not product experiments.

---

## Prod snapshot (2026-07-29)

| Signal | Value | Implication |
|--------|-------|-------------|
| Prior epoch | 496 graded @ **33.7%** (167✓/329✗) | Archive is the measurement corpus |
| Current epoch | **graded=0** | Learning health ALERT / stalled |
| Expert weights | quant=**2.0**, hype=0.96, dark_horse=1.0, technical=0.8 | Quant not reset with epoch |
| Today's pick | LONG SN15 @ 48.5% | **`ledger.gap: true`** — pick in `daily_picks.json`, no gradeable row in `predictions.json` |
| Shadows | 2 hour shadows resolving @ 100% | Excluded from trust banner + weight nudges (correct) |

### Root causes (verified in code)

| # | Issue | Where |
|---|-------|-------|
| R1 | Epoch reset clears `predictions.json` but keeps today's `daily_picks.json` | ops script / manual reset |
| R2 | Day pick records `horizon_hours=4` while UI/copy implies 24h | `internal/learning/prediction_loop.py` L226 |
| R3 | Grading is direction-only (sign of `actual_pct`) | `internal/council/grading.py` |
| R4 | Ranking objective ≠ grading objective (expert scores vs `predicted_pct`) | council score vs `signal_impact` |
| R5 | Online weight nudge cap leaves quant at 2.0 | `internal/council/weights.py` |
| R6 | No intraday **segment** memory — only instantaneous phase | pump ladder + pump_tracker |

---

## Execution order

```text
Acc-0  Ledger plumbing + epoch footgun     ← urgent, unblocks graded>0
  → Acc-1  Archive measurement script      ← read-only, informs Acc-2
  → Acc-2  One evidence-backed experiment  ← single knob, forward-only

PP-0   Segment ledger (price waveform)     ← can start parallel to Acc-0
  → PP-1  Pattern taxonomy + classifier
  → PP-2  Pump desk + council surfaces
```

**Hard gates**

- Do not start **Acc-2** until Acc-1 report is attached to PR body.
- Do not start **PP-2** until PP-1 has ≥1 self-check test with fixture waveform.
- **Acc-2** and **PP-2** are independent — either can ship first after its -1 phase.

---

## Babysit contract

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh acc0
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh acc1
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh pp0
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh pp1
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh pp2
```

Minimum every phase: health 3/3 · `ops/live` worker alive · phase asserts below.

---

## Track A — Call accuracy (Acc)

### Phase Acc-0 — Ledger plumbing + epoch footgun

**Branch:** `cursor/acc0-ledger-plumbing-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `internal/learning/prediction_loop.py`, `internal/learning/loop_health.py`, `scripts/reset_accuracy_epoch.py` (new or extend), `internal/council/daily_pick_engine.py`, tests

#### Work

| ID | Change |
|----|--------|
| Acc0-1 | **Backfill helper** — if today's published LONG exists in `daily_picks.json` but `_day_ledger_present()` is false, idempotently append the missing council day row (reuse `record_prediction_from_pick`) |
| Acc0-2 | **Epoch reset hook** — when archiving `predictions.json`, either (a) re-record today's pick immediately, or (b) set `daily_picks.json` action to HOLD with `reset_note` — never leave LONG without ledger row |
| Acc0-3 | **Boot-time heal** — resolver scheduler or worker boot calls backfill once (cheap JSON probe, same as `loop_health`) |
| Acc0-4 | **Ops script** — `scripts/heal_daily_pick_ledger.py --apply` for manual prod fix (dry-run default) |
| Acc0-5 | Tests: `test_acc0_ledger_heal.py` — gap true → heal → gap false; epoch reset simulation |

#### Acceptance criteria

- [ ] Prod `GET /api/learning/health` → `ledger.gap: false` when today's pick is LONG
- [ ] `build_learning_loop_health()` status not `stalled` solely due to ledger gap
- [ ] Re-running heal is idempotent (no duplicate pending rows for same netuid+horizon+day)
- [ ] `pytest tests/test_acc0_ledger_heal.py tests/test_learning_loop_health.py -q` green

#### Babysit Acc-0

```bash
curl -fsS "$BASE/api/learning/health" | python3 -c "
import json,sys; d=json.load(sys.stdin)
lg=d.get('ledger') or {}
print('ledger.gap=', lg.get('gap'), 'required=', lg.get('required'))
assert lg.get('gap') is not True, 'ledger gap still true'
"
```

**Human:** Confirm hero LONG SN15 (or current pick) has matching row in worker `predictions.json` pending list.

---

### Phase Acc-1 — Archive measurement (read-only)

**Branch:** `cursor/acc1-archive-measure-7728`  
**Model:** Composer 2.5-fast (script) + Grok high (interpretation LOCK only)  
**Touches:** `scripts/measure_accuracy_archive.py` (new), `data/predictions_archive/` (read-only), `cursor-agents-communication/acc1-report.md` (generated artifact)

#### Work

| ID | Change |
|----|--------|
| Acc1-1 | Load `data/predictions_archive/pre-epoch-*` + any merged resolved rows |
| Acc1-2 | Re-simulate outcomes at **4h vs 24h** horizons from stored `reference_price` + price cache / candles |
| Acc1-3 | Breakdown tables: expert, confidence decile, `phase_at_prediction`, `pick_source` (council vs shadow vs pump_lead), magnitude error bins |
| Acc1-4 | Output markdown report + JSON summary to `data/learning_outcomes/acc1_archive_summary.json` |
| Acc1-5 | No weight changes, no prod writes — analysis only |

#### Acceptance criteria

- [ ] Script runs locally: `python scripts/measure_accuracy_archive.py --archive data/predictions_archive/pre-epoch-2026-07-29`
- [ ] Report answers: "Would 24h horizon have improved headline accuracy vs 4h?"
- [ ] Report answers: "Which expert was net-negative in the epoch?"
- [ ] Report answers: "What % of misses were small-magnitude wrong-sign (noise)?"
- [ ] `acc1-report.md` committed or attached to PR (no `data/*.json` blobs in git)

#### Babysit Acc-1

- Script artifact exists on worker or in PR
- `GET /api/ops/evidence` still 200 (no regression)

**Human:** Read `acc1-report.md` top 3 recommendations — pick Acc-2 knob.

---

### Phase Acc-2 — One evidence-backed experiment

**Branch:** `cursor/acc2-accuracy-experiment-7728`  
**Model:** Composer 2.5-fast  
**Gate:** Acc-1 report must name the winning knob

#### Candidate experiments (pick exactly one based on Acc-1)

| Knob | If Acc-1 shows… | Change |
|------|-----------------|--------|
| **A — Horizon align** | 24h sim accuracy ≫ 4h on day picks | Day picks record `horizon_hours=24`; resolver uses it; UI copy matches |
| **B — Weight soft-reset** | quant net-negative, weights stale | Floor quant to 1.0, cap 1.5 for 14d forward-only epoch |
| **C — Magnitude guard** | >40% misses are \|actual\|<1% wrong-sign | Add `min_move_pct` gate before direction grade counts as miss |
| **D — Publish gate tighten** | sub-45% confidence bucket is net-negative | Raise `publish_gate` from 40% → 50% for day picks only |

#### Work (whichever knob wins)

| ID | Change |
|----|--------|
| Acc2-1 | Implement single knob with env override for rollback (`ACC2_HORIZON_HOURS=24`, etc.) |
| Acc2-2 | Forward-only: no retroactive regrade of archive |
| Acc2-3 | Trust banner + `/api/learning/stats` reflect new logic |
| Acc2-4 | Tests proving knob behavior + contract green |
| Acc2-5 | Ditto STATUS notes experiment id + rollback env |

#### Acceptance criteria

- [ ] PR cites Acc-1 table that justified the knob
- [ ] Rollback documented in PR body (one env var or revert commit)
- [ ] No new `ledger.gap` regressions
- [ ] `pytest` targeted + contract green

#### Babysit Acc-2

- `GET /api/learning/stats` — graded increments as picks resolve
- `GET /api/daily-pick` — horizon/confidence consistent with experiment

**Human:** Soak 48h — if graded accuracy after n≥20 is below 35%, rollback knob.

---

## Track B — Pump pattern tracking (PP)

### Problem statement

Traders think in **waveforms**, not ladder ticks:

> "It pumped for 2 hours, dropped for 1, then pumped again for 45 minutes."

Today we have:

| System | What it tracks | Gap |
|--------|----------------|-----|
| Pump ladder (`internal/pump/state.py`) | 5-phase state + 36-point `score_trail` | No segment durations or direction legs |
| Pump tracker (`internal/pump_tracker/core.py`) | Phase transitions + `typical_pattern` (3-phase sequence) | Coarse phases, not minute legs |
| CUSUM tracker (`datastore/pump_tracker.py`) | Wyckoff cycles + `re_pump_rate` | Separate model, not wired to desk cards |
| Council | `phase_at_prediction` snapshot | Point-in-time only |

**Goal:** Unified **segment ledger** per subnet → **pattern classes** → pump desk chips + council context.

---

### Phase PP-0 — Segment ledger (waveform memory)

**Branch:** `cursor/pp0-segment-ledger-7728`  
**Model:** Composer 2.5-fast  
**Touches:** `internal/pump/pattern_ledger.py` (new), `internal/pump/state.py` or scheduler hook, `data/pump_pattern_ledger.json`, tests

#### Design

**Segment** — contiguous directional leg derived from price (primary) or composite score (fallback):

```json
{
  "direction": "up",
  "start": "2026-07-29T14:00:00Z",
  "end": "2026-07-29T16:00:00Z",
  "duration_min": 120,
  "magnitude_pct": 4.2,
  "phase_overlay": "PUMPING"
}
```

**Rules**

- Sample on existing ladder scan cadence (no new scheduler)
- Direction from rolling return vs noise band: `|ret| < 0.3%` → `flat` (configurable)
- Close segment on direction flip or phase exit to COOLING
- Keep last **48 segments** per subnet / last **24h** (whichever smaller)
- Persist to `data/pump_pattern_ledger.json` (same volume as pump ladder)

#### Work

| ID | Change |
|----|--------|
| PP0-1 | `internal/pump/pattern_ledger.py` — `append_sample()`, `close_segment()`, `waveform(netuid)`, `load`/`save` |
| PP0-2 | Hook from `transition_subnet()` after price known — one sample per scan |
| PP0-3 | `GET /api/pump-patterns/{netuid}` — returns active waveform + segments |
| PP0-4 | Trail event `pump_segment_close` (optional, env-gated) |
| PP0-5 | Tests with synthetic price series: 2h up, 1h down, 45m up → 3 segments |

#### Acceptance criteria

- [ ] SN with known pump shows ≥2 segments in API after scan
- [ ] Segment durations sum approximately to elapsed time (±1 scan interval)
- [ ] Idempotent across restarts (persisted JSON)
- [ ] No new background scheduler
- [ ] `pytest tests/test_pump_pattern_ledger.py -q` green

#### Babysit PP-0

```bash
curl -fsS "$BASE/api/pump-patterns/15" | python3 -c "
import json,sys; d=json.load(sys.stdin)
segs=d.get('segments') or []
print('segments=', len(segs))
assert 'waveform' in d
"
```

---

### Phase PP-1 — Pattern taxonomy + classifier

**Branch:** `cursor/pp1-pattern-classes-7728`  
**Model:** Composer 2.5-fast  
**Prereq:** PP-0 merged

#### Pattern classes (v1 taxonomy)

Classify from the last 3–5 segments (direction + duration buckets):

| Class | Signature | Trader label |
|-------|-----------|--------------|
| `PUMP_ONLY` | up | Single leg |
| `PUMP_DROP` | up → down | Pump-fade |
| `PUMP_DROP_RE_PUMP` | up → down → up | **User example** — double tap |
| `DROP_RELIEF` | down → up | Relief bounce |
| `GRIND_UP` | ≥3 up legs, total up > 3% | Stair-step |
| `CHOP` | ≥4 alternating legs, net < 1% | Noise / avoid |
| `FLAT_COIL` | flat → up | Coil breakout |

**Encoding** — human + machine:

- Machine: `PUMP_DROP_RE_PUMP` + `shape_hash` (direction sequence)
- Human chip: `↑2h → ↓1h → ↑45m` (bucket durations: m < 45m, h rounded)

#### Work

| ID | Change |
|----|--------|
| PP1-1 | `classify_waveform(segments) -> PatternMatch` with confidence + label |
| PP1-2 | Subnet **behavior profile**: typical class from last 30d segments (rolling) |
| PP1-3 | `re_pump_prob` upgrade: use class `PUMP_DROP_RE_PUMP` history not just phase |
| PP1-4 | Extend `GET /api/pump-patterns/{netuid}` with `pattern_class`, `pattern_label`, `confidence` |
| PP1-5 | Tests: fixture waveforms → expected class |

#### Acceptance criteria

- [ ] Classifier returns `insufficient_data` when <2 segments
- [ ] User example waveform → `PUMP_DROP_RE_PUMP` with readable label
- [ ] `typical_pattern` on pump_tracker profile aligned or superseded (document which wins)

#### Babysit PP-1

- API returns `pattern_class` for a hot subnet
- No council weight changes

---

### Phase PP-2 — Pump desk + council surfaces

**Branch:** `cursor/pp2-pattern-surfaces-7728`  
**Model:** Composer 2.5-fast  
**Prereq:** PP-1 merged

#### Work

| ID | Change |
|----|--------|
| PP2-1 | **Pump desk card** — pattern chip under phase badge: `↑2h → ↓1h → ↑45m` + class tooltip |
| PP2-2 | **Pump desk hero** — highlight when class ∈ `{PUMP_DROP_RE_PUMP, FLAT_COIL}` and phase ∈ `{STIRRING, ACCUMULATING}` |
| PP2-3 | **Council** — attach `pattern_at_prediction` + `pattern_label` on `record_prediction_from_pick` (like `phase_at_prediction`) |
| PP2-4 | **Scenario memory** — tag picks with pattern class for postmortem |
| PP2-5 | **SSR** — pattern chip in pump desk partial (degraded empty if API slow) |
| PP2-6 | Tests: template grep + API contract for `/api/pump-patterns/*` |

#### Acceptance criteria

- [ ] Pump desk shows pattern chip for top card when segments exist
- [ ] Council prediction row includes `pattern_at_prediction` when available
- [ ] 390px: chip truncates gracefully (no layout break)
- [ ] HOLD / quiet states unchanged

#### Babysit PP-2

```bash
html=$(curl -fsS "$BASE/pump-desk")
echo "$html" | grep -q 'pump-pattern' && echo "pattern chip SSR: present" || echo "WARN: pattern chip missing"
curl -fsS "$BASE/api/pump-patterns/active" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('active patterns:', len(d.get('items') or []))
"
```

**Human:** 390px pump desk — pattern chip readable on lead card; council dossier shows pattern when present.

---

## Cross-track integration

| Integration | When | What |
|-------------|------|------|
| Acc-1 × PP-1 | After both -1 phases | Correlate `pattern_at_prediction` with council hit rate |
| Acc-2 × PP-2 | Optional follow-up | Tighten publish gate when pattern class = `CHOP` |
| Finish-queue Slice 4 | After Acc-0 | `graded > 0` unblocks combined-angles effectiveness |

---

## Ownership + conflict surface

| Agent | Owns | Do not touch |
|-------|------|--------------|
| A (-843d) | Acc-* , PP-* in `internal/learning/*`, `internal/pump/pattern_*`, council prediction hooks | B's whales/oracle/analytics |
| B (-e78a) | Price feed cadence if segment sampling needs fresher ticks | `internal/learning/routes.py` weight endpoints |

**Conflict surface:** `server.py` (new routes), `tests/test_endpoint_contract.py`, `static/js/cockpit_hydrate.js` (pump desk chips)

---

## PR checklist (every phase)

1. Branch `cursor/<slug>-7728` off latest `main`
2. Targeted `pytest` + contract
3. Push → PR → CI green → merge
4. Wait deploy (~3–5 min)
5. `./scripts/babysit_phase.sh <phase>`
6. Human spot-check per phase AC
7. Ditto STATUS + `board.md` row

---

## Suggested queue (after LC/LD)

```text
Acc-0  (urgent — fixes ledger.gap)
PP-0   (parallel — segment ledger)
  → LC → LD  (launch trust — can overlap Acc-0)
Acc-1  (after Acc-0)
PP-1   (after PP-0)
Acc-2  (after Acc-1 human knob pick)
PP-2   (after PP-1)
```

---

## References

- `internal/learning/loop_health.py` — `ledger.gap` probe
- `internal/learning/prediction_loop.py` — `horizon_hours`, `phase_at_prediction`
- `internal/pump/state.py` — ladder + `score_trail`
- `internal/pump_tracker/core.py` — `_typical_pattern`, `re_pump_rate`
- `internal/learning/pump_lead_ledger.py` — pump desk grading (separate from council)
- `finish-queue-plan.md` Slice 4 — gated on `graded > 0`
- `gameplan-pump-site-undeniable.md` — pump desk north star
- `docs/sciweave-answers-phase-j.md` — grading / horizon guidance
