# Subnet Dashboard Master Plan

**Last updated:** 2026-07-15T06:45:00Z  
**main:** `e8547b9`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Agent boot files
1. `cursor-agents-communication/board.md`
2. `cursor-agents-communication/model-guide.md` — **Composer vs Grok per phase**
3. `cursor-agents-communication/shared-workspace.md`
4. `cursor-agents-communication/ditto-phase-l-handoff.md` — Ditto planning request

## Phase Order
1. **J** → Accuracy fix + tests
2. **H-full** → Premium UI cockpit restoration
3. **K** → CI quality gates
4. **L** → Real-time signals & alerts

> **H-thin** (PR #104) partial shell on `main`. **H-full** complete (PR #120). Optional lane (PR #125).

## Completion Snapshot (`main` @ `e8547b9`)
| Phase | Status |
|-------|--------|
| J | ✅ merged (PR #105) |
| H-thin | ✅ merged (PR #104) |
| K | ✅ merged (PR #107) |
| H-full | ✅ merged (PR #120, #131) |
| H-full optional lane | ✅ merged (PR #125) |
| Model guide | ✅ merged (PR #122) |
| L | ✅ merged (PR #115, #133; UI #135) |
| **M** | ✅ merged (PR #136) |
| **N** | ✅ COMPLETE — Agent A #227 + Agent B #228 (2026-07-15) |
| **O** | ✅ COMPLETE — Agent A #227 + Agent B #228 (2026-07-15) |
| **P** | ✅ COMPLETE — prod flags on + N1 subnet_snapshot persistence (#232, #234) |

## Model selection (Composer vs Grok)
**Canonical:** `cursor-agents-communication/model-guide.md`

| Default | Switch to Grok |
|---------|----------------|
| Composer — implementation, templates, routes, CI | L WebSocket + rules design; M/N/O kickoff; read-only audits |

Phase L: Composer slices 1–2; **Grok design before** slices 3–4 (WebSocket, rules engine).

## Phase Responsibilities

### J — done

### H-full — done (Agent A)

### K — done

### M — merged (Agent A)
- Social live ingestion on `main` (PR #136).
- Telegram listener, dedup, `GET /api/message-intel`, Jinja context.
- Design: `cursor-agents-communication/phase-m-design.md`

### N / O — complete (2026-07-15)
- Agent A (`-843d`) owns N2/N3/O1/O4/O5; Agent B (`-e78a`) owns N1/N4/O2/O3.
- Full spec: `cursor-agents-communication/gameplan-N-O.md`.
- Models: Composer 2.5 default build; **Grok slow + medium** default; escalate to **high** only if medium fails or is unsatisfactory (see `model-guide.md` + `gameplan-N-O.md` §5).
- Status: ✅ COMPLETE (#227 + #228).

### P — complete (Agent A, 2026-07-15)
- Activated prod flags `CALIBRATION_AUTO_RETRAIN=on`, `CONVICTION_ALERTS_ENABLED=on` (fly.toml).
- N1 council hardening: `subnet_snapshot` + `judge_scores_at_creation` persisted on new predictions; `hybrid_score()` stub in `internal/council/grading.py`.
- Docs: `gameplan-phase-p.md`, `DEPLOY.md`, board/STATUS. Full spec: `cursor-agents-communication/gameplan-phase-p.md`.

## Sequencing Rules
- No overlap: Agent A frontend vs Agent B backend paths.
- L stable on `main` before M/N/O.

## Non-Negotiables
- Honest-empty > decorative summaries > 500 errors.
- No fake live data or fabricated signals.
- **Cache during builds** — read binding specs once; scope context; batch Grok calls; cite paths instead of re-pasting docs (`model-guide.md` → Build caching).

## Extended Reference
- Full history: `docs/master-plan-merged.md`
- UI spec: `docs/premium-dashboard-redesign.md`
- Board: `cursor-agents-communication/board.md`

## Next roadmap slice (§16) — Close the trust gap (DRAFT)

**Do not implement until approved.** Full spec: `cursor-agents-communication/gameplan-phase-16.md`.

| Slice | What | Out of scope |
|-------|------|--------------|
| **16.1** | Finish outcome backfill — every resolvable past pick gets right/wrong (N2 leftover) | New features |
| **16.2** | Real data-backed `hybrid_score()`; if `n < min_sample` → honest “not enough data yet” | UI redesigns |
| **16.3** | Re-run backtest / `verify_prod.sh`; report post-calibration win rate vs Phase P baseline | Extra signals |

Owner: Agent A (`-843d`). Sequential: 16.1 → 16.2 → 16.3.