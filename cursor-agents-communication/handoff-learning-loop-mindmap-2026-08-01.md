# Handoff — Learning loop + mindmap wiring (2026-08-01)

**STATUS:** Phase A/B open PRs ready · Phase C NEXT · **models = Grok lock → Composer build → Sonnet final review only**  
**main:** `73a0736` (Phase 1 soul_map I/O gateway #718) · later commits may land as #719–#721 merge

## Model plan (HARD — usage limit)

| Role | Model | Notes |
|------|-------|-------|
| Design LOCK | **Grok** slow + medium (high only after FAIL) | Short structured lock only — no long prose plans |
| Build / tests | **Composer 2.5** (`composer-2.5`, not fast unless trivial) | Implements lock mechanically; expands lock into PR body |
| Final review (pre-push only) | **Sonnet** | Read-only reviewer: diffs, risks, missing tests, lock deviations. **Does not edit code.** |
| Fix after Sonnet findings | **Grok lock → Composer build** again | Sonnet findings become a new Grok LOCK; Composer patches. Never let Sonnet author the fix itself. |

**Pipeline:** Grok LOCK → Composer build → orchestrator smoke-verify (diff scope / rerun new tests) → **Sonnet final review** → if findings: Grok LOCK → Composer fix → Sonnet re-review → only then commit/push/PR.

Composer fast only for pure mechanical glue after lock is frozen. Do not invent design Composer-side. Do not use Sonnet as the long primary babysitter or implementer.

## Open PRs (merge order)

| # | Branch | Title | CI | Mergeable | Notes |
|---|--------|-------|----|-----------|-------|
| **#719** | `cursor/soul-map-cache-6226` | Phase 2: cache soul_map.json reads | smoke SUCCESS | MERGEABLE | Rebased onto #718 squash. Ready. |
| **#720** | `cursor/judge-confidence-weights-6226` | Phase A: Judges confidence weights | smoke SUCCESS | MERGEABLE | Rebased; stray MI-AR lock commit **removed** from tip. Ready. |
| **#721** | `cursor/message-intel-author-reliability-6226` | Phase B: Telegram author trust | smoke SUCCESS | MERGEABLE | Ready for review. Cut from `main` (independent of #720). |

**Suggested merge order:** #719 → #720 → #721 (720 currently still contains rebased Phase 2 commit in its history if rebased onto pre-#719 tip — after #719 merges, rebase #720 onto new main if GitHub shows conflict). #721 was cut from main without Phase 2 / Judges and should merge cleanly either order vs those.

Human merges via GitHub UI (agent cannot merge). After each merge: babysit Fly deploy + curl `/health` + spot-check mindmap/home.

## Done (already on main or in PRs)

### Prod stability (earlier this session)
Event-loop wedges fixed (#710–#717): TaoStats hot-path, pump lock vs soul_map write, mindmap/graph threadpool+cache, learning routes, cockpit stream, message-intel routes.

### Phase 1 — soul_map I/O gateway — **MERGED #718**
`internal/store/soul_map_io.py`: `read_soul_map` / `write_soul_map` (per-path lock, atomic write). Writers consolidated.

### Phase 2 — soul_map read cache — **PR #719**
In-process cache in `soul_map_io.py` only. Write refreshes cache; `SOUL_MAP_CACHE_TTL` default 5s for cross-process worker. Deep copies in/out. Tests in `tests/test_soul_map_io.py` (10).

### Phase A — Judges closed loop — **PR #720**
`internal/judges/weights.py`: per-judge weights, default `0.35/0.30/0.35`. Nudge from each judge’s `closed["pnl_pct"] > 0` in `tracker.on_prediction_resolved`. `score_subnet` reads `normalized_judge_weights()`. Cold-start identical. Tests: `tests/test_judge_weights.py` (10).

**Do not confuse with** `resolver._nudge_weights_from_judge_audit` (expert soft-credit, deliberately not live).

### Phase B — Telegram Pulse closed loop — **PR #721**
**Did NOT** re-enable LB-8 quarantined `SelfLearning.start_background_learning` (that fights council `nudge_expert`). Instead:
- Incremental `increment_author_reliability` in `message_intel/models.py`
- Hook in live `PriceTracker.check_outcomes` after `save_price_outcome`
- Bounded trust multiplier in `internal/message_intel/jury.py` (`AUTHOR_TRUST_RAMP_N=20`, `AUTHOR_TRUST_MAX_SWING=0.4` → multiplier [0.8, 1.2])
- Thread `author_id` in `engine.ingest_message` + `ingest_batch`
- Tests: `tests/test_message_intel_author_reliability.py` (11)
- Lock archive: `cursor-agents-communication/message-intel-author-reliability-lock.md`

## Trail ≠ learning loop (audit summary)

| System | Closed loop? |
|--------|----------------|
| Council picks | YES |
| Pump Desk | YES |
| Judges | YES after #720 |
| Telegram Pulse | YES after #721 (author trust only; LB-8 still quarantined) |
| Dev Signals | NO loop (display-only) |

## Phase C — NEXT (mindmap / display wiring)

Pure display — no weight math. Grok-lock then Composer-build.

Wire into mindmap summary / trail / cause-chain as appropriate:

1. **Dev Signals** — `data/dev_radar_cache.json` → `/api/mindmap/summary` or trail on notable spikes (no prediction loop).
2. **Judges portfolios/postmortems** — already emit trail events; surface portfolio/postmortem summary in mindmap summary (files: `judge_portfolios.json`, `postmortems/*.json`). Optionally show new `judge_weights` after #720 merges.
3. **message_intel** — mindmap already gets soul_map bridge; optional summary block for author reliability trend after #721.
4. **Pump desk snapshots** — `data/pump_desk/snapshots/` display gap.
5. **`store.db::trail_rows`** — recommend **retire/ignore** (nothing reads it; `learning_trail` JSON is live). Do not dual-wire.

Cause-chain “Judges” step is council experts (quant/hype/dark_horse/technical), not Oracle/Echo/Pulse — do not “fix” by conflating those without a deliberate product decision.

## Verification discipline (keep)

After every Composer build, orchestrator must:
1. `git status` — only intended files
2. Read high-risk diffs line-by-line
3. Rerun new + nearby tests yourself
4. Full suite: stash before/after, **failure-NAME** `comm` diff (suite is flaky ~60–70 fails; counts alone lie)
5. Never re-enable LB-8 SelfLearning start from boot/server

## Explicit non-goals / traps

- Do not call `adjust_jury_weights` / `discover_patterns` / `start_background_learning` from prod
- Do not use shared prediction `wrong` for per-judge nudges (use `pnl_pct`)
- Do not invent a second “correct prediction” rule for message-intel — reuse `SelfLearning._is_correct_prediction`
- Squash-merge of #718 caused divergent history on #719/#720 — already rebased once; rebase again after each squash merge if needed

## HANDOFF PROMPT (paste into a new chat)

```
Continue subnet-dashboard work from handoff:
cursor-agents-communication/handoff-learning-loop-mindmap-2026-08-01.md

MODELS (usage limit — mandatory):
- Grok (Task subagent, slow+medium; high only after FAIL) → short structured LOCK only
- Composer 2.5 (not fast unless trivial) → implement lock + tests
- Sonnet = FINAL REVIEWER ONLY before push (read-only: diffs/risks/missing tests/lock drift). Sonnet does NOT edit.
- If Sonnet finds issues → Grok writes a fix LOCK → Composer implements (never Sonnet-as-implementer)
- Do NOT use Sonnet as the long primary babysitter or coder
- Before Sonnet review: orchestrator smoke-checks Composer (diff scope, rerun new tests). After green Sonnet (or Grok/Composer fix cycle): commit/push/PR

OPEN PRs — merge via GitHub UI (agent cannot merge), babysit deploy after each:
1. #719 Phase 2 soul_map cache — MERGEABLE, CI green (merge first)
2. #720 Phase A Judges confidence weights — MERGEABLE, CI green (rebase onto main if conflict after #719)
3. #721 Phase B Telegram author reliability — MERGEABLE, CI green

After merges: Phase C NEXT — mindmap display wiring only (no weight math):
- Dev Signals (dev_radar_cache.json)
- Judges portfolios/postmortems (+ judge_weights after #720)
- Telegram author reliability summary after #721
- Pump desk snapshots
- Prefer retire unused store.db trail_rows (do not dual-wire)

HARD CONSTRAINTS:
- LB-8: never start SelfLearning.start_background_learning / adjust_jury_weights from boot/server
- Ponytail: minimal diffs, reuse patterns
- Conflict surface only: server.py include_router + tests/test_endpoint_contract.py
- Branch names: cursor/<name>-6226

Read board.md + this handoff first. Search Ditto for "Cursor Agents Communication" STATUS. Then: merge babysit OR start Phase C (Grok lock → Composer build → Sonnet review → push).
```
