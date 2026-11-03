# R0.6 / Fix 6 — model config field name (UNVERIFIED at runtime)

**Branch evidence:** `review-gate-bot/tests/model-config-evidence.test.ts`

| Claim | Status |
|-------|--------|
| PR #1522 exam branch used `id: "effort"` in `bot/agent.ts` | Verified via `git show origin/agent/pr-1522-exam-r6-fixes:review-gate-bot/bot/agent.ts` |
| `@grok/agent-sdk@0.3.0 validate` accepts both `effort` and `reasoning_effort` without diagnostics | Verified locally (validate exits 0, prints "no diagnostics") |
| Host actually honors `reasoning_effort: "max"` vs silent ignore of bare `effort` | **UNVERIFIED** — no DeepSeek/registry dump in CI; production risk stays open until a host error or registry snapshot is captured |

**R0 branch posture:** `bot/agent.ts` keeps `reasoning_effort` (human override). Do not infer runtime max reasoning from validate-only evidence.

**SDK reference:** Agent SDK model config uses provider-specific keys; validate does not prove the inference backend applies them.
