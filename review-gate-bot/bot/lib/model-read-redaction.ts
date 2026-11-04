/**
 * R2 arm F: the reviewer sees repository reads without the secret scrubber.
 * GitHub posts still pass through `redactSecrets` in `post_verdict`.
 */
export function scrubModelRepoReads(): boolean {
  return (process.env.R2_METHOD_ARM ?? "A").trim().toUpperCase() !== "F";
}
