import { r2MethodArmFromEnv, type SessionPurpose } from "./method-variants.js";

/**
 * R2 arm F: eval sessions may show repository reads without the secret scrubber.
 * Live PR sessions always scrub. GitHub posts still pass through `redactSecrets`
 * in `post_verdict`.
 */
export function scrubModelRepoReads(purpose: SessionPurpose = "live"): boolean {
  if (purpose !== "eval") {
    return true;
  }
  return r2MethodArmFromEnv() !== "F";
}
