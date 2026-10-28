import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { prKey, replitAskKey } from "./gate.js";
import { exclusive } from "./lock.js";
import type { PrRef } from "./gh.js";
import { redactSecrets } from "./redact.js";

/**
 * The conditional Replit step.
 *
 * ## What is measured
 *
 * - Replit publishes a remote MCP server at `https://mcp.replit.com/server/mcp`
 *   (Streamable HTTP, OAuth protected-resource discovery). Its tool list
 *   includes `ask_question`, whose **required input is `replId` and
 *   `question`** — there is no `message` parameter. The spec's wording
 *   ("`message` exactly X") is therefore implemented as `question: "X"`: the
 *   documented parameter name wins over the sketch.
 * - The SDK wires a remote MCP server with `defineConnection({ url })` and
 *   reaches it from host code through `ctx.host.mcp.callTool(name, tool, args)`.
 *
 * ## What is inferred, and what it changes
 *
 * `ask_question` asks a question of an existing Replit app's agent context. It
 * does **not** start, wake or schedule a new Agent run, so it is not itself a
 * review dispatch and is never counted as one. The review request is the
 * `@replit review` comment; this call is only a nudge alongside it.
 *
 * There is a measured side effect worth recording, from practice rather than
 * from documentation: sending the literal question `X` through `ask_question`
 * has caused Replit to sweep its `@replit` tags. So the ask is kept — it does
 * help Replit notice — but **the gate advances only on Replit's posted
 * verdict** on the PR, never on a successful `ask_question`. `ReplitAskOutcome`
 * has no `reviewed` member for exactly that reason: there is nothing here a
 * caller could mistake for a verdict.
 *
 * ## Retry
 *
 * The ask used to run only while the gate was still on `tag_replit`. As soon as
 * the tag comment was recorded the state became `await_replit`, and an ask that
 * failed (connector not wired, MCP error, transient 5xx) was never retried —
 * permanently, silently. It now runs from `tag_replit` *and* `await_replit`,
 * records its attempt so a retry is bounded, and reports a persistent failure
 * instead of returning quietly.
 */

export const REPLIT_CONNECTION = "replit";
export const REPLIT_TOOL = "ask_question";
export const REPL_ID = "0be6701e-9662-43b1-becb-5912837e44f7";
/**
 * The nudge the gate asks. Joshua's decision (#1513): name the PR and the head, and keep Replit on the free
 * effort level. A bare question made Replit stall or search for the work, because it asked which effort to use.
 */
export function replitQuestion(prNumber: number, headSha: string): string {
  return `Review PR #${prNumber} at head \`${headSha}\`. Use the free/default effort level — do not ask which effort level to use and do not offer power mode. Post your verdict on the PR.`;
}

/** Attempts per head before the ask is reported as persistently failing. */
export const ASK_ATTEMPTS = 3;

/**
 * `ambiguous`: the call may have gone out, but nothing confirms the outcome (the record of it could not
 * be finished, or the process died mid-call). It is never retried automatically, because a retry could
 * ask Replit twice; clear the head's ask record (`replitAskKey`) to allow one more ask.
 */
export type ReplitAskFailure = "unavailable" | "no-tool" | "error" | "ambiguous";

export type ReplitAskOutcome =
  | { asked: true; text: string; attempts: number }
  | { asked: false; reason: "already-asked"; detail: string }
  | {
      asked: false;
      reason: ReplitAskFailure;
      detail: string;
      attempts: number;
      /** True once the attempt budget for this head is spent. Surface this. */
      persistent: boolean;
    };

type AskRecord = {
  /** Successful asks. Present means: do not ask again for this head. */
  askedAt?: number;
  /**
   * Written before the call and replaced by `askedAt` or a failure once the outcome is known. Still
   * present on a later read means the outcome was never confirmed, so the ask is not repeated.
   */
  inFlightAt?: number;
  /** Failed attempts, so a retry is bounded and a persistent failure is visible. */
  failedAttempts?: number;
  lastFailure?: string;
  at: number;
};

function asAskRecord(value: unknown): AskRecord | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Partial<AskRecord>;
  if (typeof record.at !== "number") {
    return undefined;
  }
  return record as AskRecord;
}

/**
 * Is the Replit connector wired and offering `ask_question`?
 *
 * Checked rather than assumed: an unwired connector must leave the Replit ask
 * with MC instead of failing a gate turn.
 */
export async function replitAvailable(mcp: HostMcpRegistry): Promise<boolean> {
  if (!mcp.names().includes(REPLIT_CONNECTION)) {
    return false;
  }
  try {
    const tools = await mcp.listTools(REPLIT_CONNECTION);
    return tools.some((tool) => tool.name === REPLIT_TOOL);
  } catch {
    return false;
  }
}

/**
 * Ask Replit once per head, retrying a failed ask on later gate events.
 *
 * Nothing here posts to GitHub and nothing here can advance the gate. A
 * success writes the kv record so no later event repeats the ask; a failure
 * increments the attempt count and comes back with `persistent: true` once the
 * budget is spent, which the channel logs loudly.
 */
export function askReplitOnce(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  // One caller at a time per (PR, head): a read of the record followed by a
  // write is not a claim, so overlapping events used to all ask, and a late
  // failure could overwrite a recorded success.
  return exclusive(replitAskKey(input.ref, input.headSha), () => askReplit(input));
}

async function askReplit(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  const key = replitAskKey(input.ref, input.headSha);
  const previous = asAskRecord(await input.kv.get(key));

  if (previous?.askedAt !== undefined) {
    return { asked: false, reason: "already-asked", detail: "recorded for this head" };
  }

  const failedAttempts = previous?.failedAttempts ?? 0;
  if (previous?.inFlightAt !== undefined) {
    // An earlier delivery wrote this before calling Replit and never recorded how the call ended. It may
    // have been sent, so asking again could ask twice. That is worse than an ask that never goes out:
    // the @replit tag is already on the PR, and the gate advances only on Replit's posted verdict.
    return {
      asked: false,
      reason: "ambiguous",
      detail: "an earlier ask for this head has no recorded outcome; not repeating it automatically",
      attempts: failedAttempts + 1,
      persistent: true,
    };
  }
  if (failedAttempts >= ASK_ATTEMPTS) {
    return {
      asked: false,
      reason: "error",
      detail: `gave up after ${failedAttempts} attempts: ${previous?.lastFailure ?? "unknown"}`,
      attempts: failedAttempts,
      persistent: true,
    };
  }

  // The detail is the connector's own text, which can echo a credential it was given. It is scrubbed
  // here, once, so the stored failure, the returned outcome and every log line that carries it are clean.
  const fail = async (reason: ReplitAskFailure, rawDetail: string): Promise<ReplitAskOutcome> => {
    const detail = redactSecrets(rawDetail).text;
    const attempts = failedAttempts + 1;
    await input.kv.put(key, {
      at: Date.now(),
      failedAttempts: attempts,
      lastFailure: `${reason}: ${detail}`.slice(0, 300),
    } satisfies AskRecord);
    return { asked: false, reason, detail, attempts, persistent: attempts >= ASK_ATTEMPTS };
  };

  if (!(await replitAvailable(input.mcp))) {
    return fail("unavailable", `no ${REPLIT_TOOL} on the "${REPLIT_CONNECTION}" connection`);
  }

  // Recorded before the call, so storage failing afterwards cannot make the ask look like it never
  // happened. If this write fails nothing has been sent, so the error propagates and a later delivery
  // starts over.
  const startedAt = Date.now();
  await input.kv.put(key, {
    at: startedAt,
    inFlightAt: startedAt,
    ...(failedAttempts > 0 ? { failedAttempts, lastFailure: previous?.lastFailure } : {}),
  } satisfies AskRecord);

  let result: Awaited<ReturnType<HostMcpRegistry["callTool"]>>;
  try {
    result = await input.mcp.callTool(REPLIT_CONNECTION, REPLIT_TOOL, {
      replId: REPL_ID,
      question: replitQuestion(input.ref.number, input.headSha),
    });
  } catch (error) {
    return fail("error", error instanceof Error ? error.message : String(error));
  }

  const text = result.content
    .map((part) => (part.type === "text" ? part.text : `<${part.type}>`))
    .join(" ");

  if (result.isError === true) {
    return fail("error", text.slice(0, 300));
  }

  // The call succeeded: Replit was asked. If the record cannot be completed, the in-flight record stays
  // and blocks a repeat; the outcome is still reported as asked, and the storage fault is logged.
  try {
    await input.kv.put(key, { at: Date.now(), askedAt: Date.now() } satisfies AskRecord);
  } catch (error) {
    console.error(
      JSON.stringify({
        level: "error",
        event: "replit_ask_record_failed",
        pr: prKey(input.ref),
        head: input.headSha,
        error: redactSecrets(error instanceof Error ? error.message : String(error)).text,
        effect: "Replit was asked, but the record could not be completed. The ask will not be repeated automatically.",
      }),
    );
  }
  return { asked: true, text: text.slice(0, 500), attempts: failedAttempts + 1 };
}
