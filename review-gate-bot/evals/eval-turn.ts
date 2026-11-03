import type { EvalTestContext } from "@grok/agent-sdk/evals";

const RETRY_CODES = new Set(["resource_exhausted", "rate_limited", "unavailable"]);
const RETRY_WAIT_MS = 15_000;

function errorCode(err: unknown): string | undefined {
  if (typeof err !== "object" || err === null) {
    return undefined;
  }
  const code = (err as { code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

/**
 * One model turn with a single retry on quota / availability errors. Other failures are left to the
 * eval result JSON (skipped / infra), not treated as a bot miss.
 */
export async function sendWithRetry(t: EvalTestContext, prompt: string, opts: Parameters<EvalTestContext["send"]>[1]): Promise<void> {
  try {
    await t.send(prompt, opts);
  } catch (first) {
    const code = errorCode(first);
    if (code === undefined || !RETRY_CODES.has(code)) {
      throw first;
    }
    t.log(`turn failed (${code}); retrying once after ${RETRY_WAIT_MS}ms`);
    await new Promise((r) => setTimeout(r, RETRY_WAIT_MS));
    await t.send(prompt, opts);
  }
}
