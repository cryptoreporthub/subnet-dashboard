# R0.7 — `review-gate-bot/bot/` vs PR #1522 head `50e231f3`

**Compare:** `git diff 50e231f36665066cbb8f3b646ec88d77bb90ded5 HEAD -- review-gate-bot/bot/`  
**Note:** `bot/instructions.md` is **unchanged** vs `50e231f3` (pinned PR-head control text). R2 arms append via `bot/instructions.ts` + `bot/lib/method-variants.ts` only.

| Path | Lines @50e231f3 → @R0 | Δ lines | Purpose (R0 exam / harness) |
|------|------------------------|---------|-------------------------------|
| `bot/agent.ts` | 38 → 53 | +15 | Composer exam agent: `reasoning_effort`, channel hooks, eval verdict-once wiring |
| `bot/hooks/skill-reads.ts` | 0 → 19 | **new** | SDK hook: enforce skill-read tracking on eval turns |
| `bot/instructions.ts` | 0 → 7 | **new** | `defineInstructions` append from `R2_METHOD_ARM` (default **A**; C eval-only) |
| `bot/lib/advance.ts` | 326 → 331 | +5 | Gate advance / tagging edge (exam stack) |
| `bot/lib/eval-verdict-once.ts` | 0 → 28 | **new** | Eval-only guard: one accepted `post_verdict` per run |
| `bot/lib/fixtures.ts` | 72 → 77 | +5 | Fixture loader notes / `baseFiles` typing |
| `bot/lib/gate.ts` | 270 → 270 | 0 | Same line count; small logic edits inside |
| `bot/lib/instruction-blocks.ts` | 0 → 61 | **new** | Verbatim owner-rules + reviewer-state blocks for arms B/D |
| `bot/lib/method-variants.ts` | 0 → 109 | **new** | R2 arms A–D on PR-head markdown + manifest hashes |
| `bot/lib/redact.ts` | 182 → 261 | +79 | Secret scrubber: assignment scan, bounded JWT pattern, nested assignments |
| `bot/lib/replit.ts` | 198 → 241 | +43 | Replit slot / question flow for exam |
| `bot/lib/repo.ts` | 262 → 262 | 0 | Minor read/scrub path tweak |
| `bot/lib/review-method.ts` | 0 → 43 | **new** | Always-loaded method markdown + skill inlining helpers |
| `bot/lib/skill-delivery.ts` | 0 → 28 | **new** | Which skills are always-delivered in arm C |
| `bot/lib/skill-reads.ts` | 0 → 99 | **new** | Skill read ledger for eval grading |
| `bot/skills/adversarial-review/SKILL.md` | 86 → 127 | +41 | Exam adversarial steps (trace production entrypoints) |
| `bot/skills/owner-rules/SKILL.md` | 53 → 66 | +13 | Owner-rule skill alignment |
| `bot/tools/compare_suite_runs.ts` | 230 → 245 | +15 | Eval branch: fixture gate suite pin (no JUnit fetch) |
| `bot/tools/post_verdict.ts` | 145 → 271 | +126 | Eval posting, marker checks, double-post prevention |
| `bot/tools/read_repo_file.ts` | 53 → 53 | 0 | **R0.8:** eval `at:base` serves `baseFiles` only (no head fallback) |

**Not pushed to #1522.** Production ship of Composer / arm defaults awaits explicit GO (PLAN-v1.2/v1.3).
