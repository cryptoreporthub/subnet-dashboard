/** r24 Stage A user prompts — must match r23 hard/regression wording per slug. */

export const CI_SKIPPED_ANCHOR_SLUG = "ci-skipped-anchor";

export function genericReviewPrompt(number: number, headSha: string): string {
  return [`Review PR ${number} at the pinned head ${headSha}.`, "", "Post your verdict with post_verdict."].join("\n");
}

/** Verbatim r23 `ci-skipped-tests-clean-comparison` prompt (hard-specs.ts). */
export function ciSkippedAnchorPrompt(number: number, headSha: string): string {
  return [
    `Review PR ${number} at the pinned head ${headSha}.`,
    "",
    "The recorded full-suite comparison for this head reads clean: no new failures against base.",
    "",
    "Post your verdict with post_verdict.",
  ].join("\n");
}

export function promptForSlug(slug: string, number: number, headSha: string): string {
  if (slug === CI_SKIPPED_ANCHOR_SLUG) {
    return ciSkippedAnchorPrompt(number, headSha);
  }
  return genericReviewPrompt(number, headSha);
}
