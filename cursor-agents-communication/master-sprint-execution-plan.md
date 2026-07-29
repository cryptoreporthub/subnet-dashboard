# Master sprint — LC/LD + Acc + PP (merge → babysit → review)

**Status:** ACTIVE  
**Created:** 2026-07-29  
**Baseline main:** `2ee0512`  
**Canon:** `launch-lc-ld-plan.md` · `accuracy-pump-pattern-plan.md` · `finish-queue-plan.md` · `board.md`  
**Rule:** **One phase → one PR → merge → deploy (~5 min) → babysit → human review → next phase.**  
No stacking unmerged implementation PRs. If babysit fails, **stop** — fix or rollback before continuing.

---

## What “all of it” covers

| Track | Phases | Outcome |
|-------|--------|---------|
| **Launch trust** | LC → LD | NFA, robots.txt, OG PNG, surface honesty |
| **Call accuracy** | Acc-0 → Acc-1 → Acc-2 | Ledger heal, archive truth, one experiment |
| **Pump patterns** | PP-0 → PP-1 → PP-2 | Waveform memory, pattern classes, desk + council |
| **Finish queue** | FQ-4 | Combined-angles effectiveness (after `graded > 0`) |

**Out of scope this sprint:** Chutes billing, payment tiers, Aug 4 soak sign-off (H2), SS-TG 390px fixes unless H1 fails (Slice 5).

---

## Babysit quick reference

```bash
# After every merge (replace <phase>):
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh <phase>

# Cumulative smoke after multiple phases shipped:
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint

# Learning loop extra (optional):
curl -fsS "$BASE/api/learning/health" | python3 -m json.tool
```

| Phase | Babysit arg | Pass means |
|-------|-------------|------------|
| Baseline | `sprint` (pre-work) | health 3/3, worker alive, LA+LB still green |
| Acc-0 | `acc0` | `ledger.gap` false when LONG published |
| PP-0 | `pp0` | `/api/pump-patterns/{netuid}` returns segments |
| LC | `lc` | robots.txt 200, NFA + og-share in HTML |
| LD | `ld` | no dead alert CTA, portfolio API 200 |
| Acc-1 | `acc1` | archive script present, ops/evidence OK |
| PP-1 | `pp1` | `pattern_class` on pattern API |
| Acc-2 | `acc2` | stats/horizon match experiment (see phase doc) |
| PP-2 | `pp2` | pattern chip on pump desk |
| FQ-4 | `fq4` | combined-angles artifact + graded > 0 |
| Full rollup | `sprint` | all shipped phases above |

**If babysit fails:** open hotfix PR on same phase branch pattern → merge → re-babysit. Do **not** start next phase.

---

## Execution queue (numbered — follow in order)

```text
M0   Merge plan PRs (#647 + #646)
  ↓
1    Acc-0   ledger plumbing          babysit acc0   → REVIEW-R1
  ↓
2    PP-0    segment ledger           babysit pp0    → REVIEW-R2
  ↓
3    LC      legal / trust / SEO      babysit lc     → REVIEW-R3
  ↓
4    LD      surface honesty          babysit ld     → REVIEW-R4
  ↓
5    Acc-1   archive measurement      babysit acc1   → REVIEW-R5 (human picks Acc-2 knob)
  ↓
6    PP-1    pattern taxonomy         babysit pp1    → REVIEW-R6
  ↓
7    Acc-2   one accuracy experiment  babysit acc2   → REVIEW-R7 (48h soak)
  ↓
8    PP-2    desk + council surfaces  babysit pp2    → REVIEW-R8
  ↓
9    FQ-4    combined angles artifact babysit fq4    → REVIEW-R9
  ↓
DONE  ./scripts/babysit_phase.sh sprint + Ditto STATUS
```

**Why this order**

1. **Acc-0 first** — prod `ledger.gap` blocks trustworthy learning metrics (finish-queue Slice 4).
2. **PP-0 before LC** — pure backend/json; no template conflict with LC/LD.
3. **LC → LD** — launch trust before heavier UI (PP-2 touches pump desk JS).
4. **Acc-1 before Acc-2** — evidence before experiment.
5. **PP-1 before PP-2** — classifier before chips.
6. **FQ-4 last** — needs `graded > 0` from Acc-0 + at least one resolved pick.

---

## M0 — Merge plan docs (no code)

| Item | PR | Action |
|------|-----|--------|
| Acc + PP plan | #647 | Merge to `main` |
| LC + LD plan | #646 | Merge to `main` |

**Babysit:** `./scripts/babysit_phase.sh sprint` (baseline only — LA/LB/C checks)  
**Human review:** Skim both plan docs; confirm queue order above.

---

## Step 1 — Acc-0: Ledger plumbing

**Branch:** `cursor/acc0-ledger-plumbing-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § Acc-0

| Deliverable | Verify |
|-------------|--------|
| Backfill today's LONG into `predictions.json` | `ledger.gap: false` |
| Epoch reset hook (no orphan LONG) | unit test |
| `scripts/heal_daily_pick_ledger.py --dry-run` | ops runbook |

**PR:** CI green → merge → wait deploy  
**Babysit:** `./scripts/babysit_phase.sh acc0`  
**Human REVIEW-R1:** `GET /api/learning/health` — status not `stalled` from gap; confirm one pending day row for today's netuid.

---

## Step 2 — PP-0: Segment ledger

**Branch:** `cursor/pp0-segment-ledger-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § PP-0

| Deliverable | Verify |
|-------------|--------|
| `internal/pump/pattern_ledger.py` | segments persist across restart |
| `GET /api/pump-patterns/{netuid}` | waveform JSON |
| Hook on ladder scan | no new scheduler |

**Babysit:** `./scripts/babysit_phase.sh pp0`  
**Human REVIEW-R2:** Hit a hot subnet API — see ≥2 segments after a few scans; durations plausible.

---

## Step 3 — LC: Legal / trust / SEO

**Branch:** `cursor/launch-lc-trust-seo-7728`  
**Detail:** `launch-lc-ld-plan.md` § LC

| Deliverable | Verify |
|-------------|--------|
| NFA footer | view-source `/` |
| `GET /robots.txt` | 200 |
| `static/og-share.png` | social preview |
| CSP fonts | no console CSP errors |

**Babysit:** `./scripts/babysit_phase.sh lc`  
**Human REVIEW-R3:** Link preview (Discord/Telegram/iMessage) shows PNG card.

---

## Step 4 — LD: Surface honesty

**Branch:** `cursor/launch-ld-surface-honesty-7728`  
**Detail:** `launch-lc-ld-plan.md` § LD  
**Gate:** LC babysit green

| Deliverable | Verify |
|-------------|--------|
| Hidden conviction alerts when env off | no dead CTA |
| Paper portfolio quiet state | no eternal spinner |
| HOLD cards outside hero | degraded styling |

**Babysit:** `./scripts/babysit_phase.sh ld`  
**Human REVIEW-R4:** 390px — watchlist, paper portfolio, chat degraded path; no zombie UI.

---

## Step 5 — Acc-1: Archive measurement

**Branch:** `cursor/acc1-archive-measure-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § Acc-1  
**Gate:** Acc-0 merged

| Deliverable | Verify |
|-------------|--------|
| `scripts/measure_accuracy_archive.py` | runs on pre-epoch archive |
| `acc1-report.md` | 4h vs 24h, expert breakdown, noise % |

**Babysit:** `./scripts/babysit_phase.sh acc1`  
**Human REVIEW-R5:** Read report top 3; **pick exactly one Acc-2 knob** (horizon / weights / magnitude / publish gate). Record choice in PR # for Acc-2.

---

## Step 6 — PP-1: Pattern taxonomy

**Branch:** `cursor/pp1-pattern-classes-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § PP-1  
**Gate:** PP-0 merged

| Deliverable | Verify |
|-------------|--------|
| `classify_waveform()` | `PUMP_DROP_RE_PUMP` on fixture |
| Human label `↑2h → ↓1h → ↑45m` | API field |
| Subnet behavior profile | rolling typical class |

**Babysit:** `./scripts/babysit_phase.sh pp1`  
**Human REVIEW-R6:** Spot-check 2–3 hot subnets — labels match intuition.

---

## Step 7 — Acc-2: One accuracy experiment

**Branch:** `cursor/acc2-accuracy-experiment-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § Acc-2  
**Gate:** REVIEW-R5 knob chosen; cited in PR body

| Deliverable | Verify |
|-------------|--------|
| Single knob + env rollback | documented |
| Forward-only (no archive regrade) | tests |
| Trust banner honest | `/api/learning/stats` |

**Babysit:** `./scripts/babysit_phase.sh acc2`  
**Human REVIEW-R7:** **48h soak** — if graded n≥20 and accuracy <35%, rollback env knob.

---

## Step 8 — PP-2: Pump desk + council surfaces

**Branch:** `cursor/pp2-pattern-surfaces-7728`  
**Detail:** `accuracy-pump-pattern-plan.md` § PP-2  
**Gate:** PP-1 merged

| Deliverable | Verify |
|-------------|--------|
| Pattern chip on pump desk card | SSR + hydrate |
| `pattern_at_prediction` on council rows | like `phase_at_prediction` |
| 390px truncation | no layout break |

**Babysit:** `./scripts/babysit_phase.sh pp2`  
**Human REVIEW-R8:** Pump desk lead card shows waveform chip; council dossier shows pattern when present.

---

## Step 9 — FQ-4: Combined angles effectiveness

**Branch:** `cursor/finish-slice4-combined-angles-7728`  
**Detail:** `finish-queue-plan.md` Slice 4  
**Gate:** `graded > 0` (Acc-0 + at least one resolved pick)

| Deliverable | Verify |
|-------------|--------|
| Effectiveness artifact under `data/learning_outcomes/` | ops/evidence |
| Board Slice 4 → DONE | `board.md` |

**Babysit:** `./scripts/babysit_phase.sh fq4`  
**Human REVIEW-R9:** Artifact readable; combined vs single-angle comparison makes sense.

---

## Conflict surface (rebase before merge if touched)

| File | Phases that touch it |
|------|----------------------|
| `server.py` | Acc-0, PP-0, PP-2, LC |
| `tests/test_endpoint_contract.py` | all implementation phases |
| `static/js/cockpit_hydrate.js` | LD, PP-2 |
| `cursor-agents-communication/board.md` | every phase (status row) |

**Rule:** Only one open implementation PR at a time. Plan-doc PRs (M0) merge first.

---

## PR checklist (copy for every step)

```text
[ ] Branch cursor/<slug>-7728 off latest main
[ ] Targeted pytest + contract
[ ] Push → PR (draft OK) → CI green → merge (not draft)
[ ] Wait Fly deploy ~5 min
[ ] ./scripts/babysit_phase.sh <phase>
[ ] Human REVIEW-R<n> sign-off (or fix/rollback)
[ ] Ditto save_memory STATUS (main=sha, phase DONE)
[ ] board.md row → DONE
```

---

## Human gates (calendar — not agent work)

| # | When | Blocks |
|---|------|--------|
| H1 | Now | SS-TG 390px sign-off |
| H2 | 2026-08-04 | Soak day 7 — may adjust Acc-2 rollback threshold |
| H3 | 2026-08-11 | Final soak sign-off |

---

## After sprint DONE

- `./scripts/babysit_phase.sh sprint` — full rollup green
- Finish-queue Slice 5+ only if H1 fails items
- Optional: correlate `pattern_at_prediction` × council hit rate (Acc-1 × PP-1 follow-up doc)

---

## References

- `accuracy-pump-pattern-plan.md` — Acc + PP phase detail
- `launch-lc-ld-plan.md` — LC + LD phase detail
- `finish-queue-plan.md` — Slice 4 spec
- `scripts/babysit_phase.sh` — phase probes + `sprint` rollup
