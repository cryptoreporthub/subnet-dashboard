# Council Hero — Cursor Implementation Handoff

**Repo:** `https://github.com/cryptoreporthub/subnet-dashboard`
**Scope:** One focused unit — port the *validated* Council Hero into the live template and wire it to real data. No parallel fanout; verify before merging.

## 0. What's already validated (do not redesign)
- **Monochrome grey motion "puffs"** in front of the glass card — pure CSS radial-gradient blobs (elliptical: tall/wide/round) that swell, shear, rotate, drift and breathe opacity across 3 layers. **No SVG `feTurbulence`** (removed for reliability).
- **Blue ambient glow retained BEHIND** the glass card (ice-blue bloom `card::before` + cyan-teal drift `card::after`). Grey churns in front; blue gives atmosphere behind. Keep both.
- Real **data sections below the gauge**: 1) Decision Log (verdict kind, confidence %, consensus_score vs brain_recommendation, dissent), 2) Council Accuracy · this epoch (graded/hit-miss/win-rate — must COUNT UP as gradings land), 3) Jury · last grading move (Oracle/Echo/Pulse weight movement ▲/▼/·).
- Conic confidence gauge + orbiting Oracle/Echo/Pulse nodes + flowing dashed rays.
- **Fix gauge math bug**: weights 0.40/0.30/0.30 with signals 36/32/32 → weighted verdict = **33.6%**, not 34%.

## 1. Known API gap (backend, small)
`/api/learning/stats` returns only `expert_weights` — no `judge_weights` (confirmed live). Add `judge_weights` to the payload in `internal/learning/routes.py`, mirroring `_council_weights_list()` / `expert_weights`, using `load_judge_weights()` / `normalized_judge_weights()`. Inject into `_compute_learning_metrics()` / `_learning_snapshot()`. ~15 lines. Redeploy after.

## 2. Wire hero to real data
| Hero field | Source |
|---|---|
| Verdict confidence (gauge) | council/home verdict confidence |
| Oracle/Echo/Pulse weights | `judge_weights` from `/api/learning/stats` (after §1) |
| Verdict kind badge | `verdict_kind` |
| Consensus vs brain | `consensus_score` + `brain_recommendation` |
| Dissent | council record dissent fields |
| **Accuracy ledger** | real grading stats (`graded_this_epoch`, `correct`, `win_rate`) — counts up, NOT static |
| Juror weight movement | delta of prior vs current `judge_weights` |

Remove the fake "LIVE" jitter (rewrites text without changing data) — wire to real data or present statically & honestly. Wire tabs if interactive, else suppress to active.

## 3. File targets
- Port hero into live council/home template (`tribunal_hero` / `council_stage` integration → `council_stage.html`; confirm path during implementation).
- Add pure-CSS puff + blue-glow styles to template stylesheet (no SVG turbulence).
- Keep mobile-first (390px) + `prefers-reduced-motion`.

## 4. Acceptance checks
- [ ] `/api/learning/stats` returns `judge_weights` after §1.
- [ ] Hero shows live verdict confidence, weights, decision log.
- [ ] Accuracy ledger reads real grading stats (counts up, not static).
- [ ] Gauge math correct (33.6%, not 34%).
- [ ] Grey puffs in front, blue glow behind, both visible.
- [ ] No SVG `feTurbulence` in hero.
- [ ] Mobile (390px) + reduced-motion pass.
- [ ] Homepage + `/health` still render; council page renders hero.
- [ ] Merge → Fly deploy → verify on `subnet-dashboard.fly.dev`.

## 5. Handoff note
If you need exact hero markup rather than this spec, ask the user to paste `council-hero-v4.html`. Cursor cannot reach Ditto artifact storage.
