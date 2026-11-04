/**
 * The hard specs with the clause-aware checks of grader-checks.ts in place of the inline wording patterns of the
 * same id. Used by `regrade-saved.ts` to grade saved runs; `hard-specs.ts` itself stays as the r7 exam ran it.
 */
import * as G from "./grader-checks.js";
import type { Pat } from "./hard-grading.js";
import { SPECS } from "./hard-specs.js";

const CLAUSE_AWARE: Record<string, Pat> = {
  "root-dropped": G.mechanismRootDropped,
  "claims-it-tagged-replit": G.claimsItTaggedReplit,
  "tmc-over-chain": G.mechanismTmcOverChain,
  "no-grace-clock-so-never-removed": G.mechanismNoGraceClock,
  "tests-only": G.mechanismTestsOnly,
  "boundary-before-at-after": G.mechanismBoundaryBeforeAtAfter,
  "no-secret-in-the-line": G.mechanismNoSecretInLine,
  "a-clean-comparison-is-not-evidence": G.mechanismCleanComparisonNotEvidence,
  "every-member-gets-a-grace-clock": G.mechanismEveryMemberGraceClock,
  "the-boundary-is-exact-on-the-injected-clock": G.mechanismExactClockBoundary,
  "cursor-and-ditto-are-pending-at-the-new-head": G.replyCursorDittoPending,
};

for (const spec of SPECS) {
  for (const list of [spec.cites, spec.mechanisms, spec.forbid, spec.reply, spec.replyForbid]) {
    for (const e of list ?? []) {
      const wired = CLAUSE_AWARE[e.id];
      if (wired !== undefined) {
        (e as { test: Pat }).test = wired;
      }
    }
  }
}

export { SPECS };
