import type { HostKvApi } from "@grok/agent-sdk/kv";

const KEY_PREFIX = "eval-verdict-once:";

export const evalVerdictOnceKey = (sessionId: string): string => `${KEY_PREFIX}${sessionId}`;

/** Reasons that allow another `post_verdict` attempt in the same eval turn. */
export const RETRYABLE_POST_REASONS = new Set([
  "pass-with-blocking-finding",
  "skill-not-read",
  "incomplete-skills-table",
  "pass-with-credential-value",
  "pass-with-unmeasured-perf-claim",
  "placeholder-verdict-body",
  "stale-head",
]);

export async function evalVerdictAlreadyAccepted(kv: Pick<HostKvApi, "get">, sessionId: string): Promise<boolean> {
  try {
    return (await kv.get(evalVerdictOnceKey(sessionId))) === true;
  } catch {
    return false;
  }
}

export async function markEvalVerdictAccepted(kv: Pick<HostKvApi, "put">, sessionId: string): Promise<void> {
  await kv.put(evalVerdictOnceKey(sessionId), true);
}
