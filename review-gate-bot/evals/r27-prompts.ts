/** r27 Stage C — generic review() prompt for every slug (no per-slug wording). */

export function genericReviewPrompt(number: number, headSha: string): string {
  return [`Review PR ${number} at the pinned head ${headSha}.`, "", "Post your verdict with post_verdict."].join("\n");
}

export function promptForSlug(_slug: string, number: number, headSha: string): string {
  return genericReviewPrompt(number, headSha);
}
