import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { replitAskKey } from "./gate.js";

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
 * ## What is inferred
 *
 * For a **hosted** bot the docs are explicit that `mcp oauth` tokens stay on
 * the machine that authorized them, and that a hosted agent should instead add
 * the server under MCP in the Cursor dashboard and reach it through a
 * `cursorAccount: true` connection. So `bot/host-connections/replit.ts` uses
 * the Cursor-account form, and this module treats "the connector is not set up"
 * as an expected, non-fatal state rather than an error.
 *
 * See the PR body's open questions: whether the connector name is literally
 * `Replit`, and whether the team egress policy admits `mcp.replit.com`.
 */

export const REPLIT_CONNECTION = "replit";
export const REPLIT_TOOL = "ask_question";
export const REPL_ID = "0be6701e-9662-43b1-becb-5912837e44f7";
/** The question the gate asks. Short on purpose: it is a wake-up, not a brief. */
export const REPLIT_QUESTION = "X";

export type ReplitAskOutcome =
  | { asked: true; text: string }
  | { asked: false; reason: "already-asked" | "unavailable" | "no-tool" | "error"; detail: string };

type AskRecord = { at: number; askedAt: number };

function asAskRecord(value: unknown): AskRecord | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Partial<AskRecord>;
  if (typeof record.askedAt !== "number") {
    return undefined;
  }
  return { at: typeof record.at === "number" ? record.at : record.askedAt, askedAt: record.askedAt };
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
 * Ask Replit once per head, after the @replit tag.
 *
 * The ask is invisible on GitHub, so the only record is the kv key this writes
 * on success. A lost race can therefore repeat the ask; that is acceptable
 * because the question is read-only and idempotent on Replit's side (it changes
 * no app). Nothing here posts to GitHub.
 */
export async function askReplitOnce(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  prNumber: number;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  const key = replitAskKey(input.prNumber, input.headSha);

  if (asAskRecord(await input.kv.get(key)) !== undefined) {
    return { asked: false, reason: "already-asked", detail: "recorded for this head" };
  }

  if (!(await replitAvailable(input.mcp))) {
    return {
      asked: false,
      reason: "unavailable",
      detail: `no ${REPLIT_TOOL} on the "${REPLIT_CONNECTION}" connection`,
    };
  }

  try {
    const result = await input.mcp.callTool(REPLIT_CONNECTION, REPLIT_TOOL, {
      replId: REPL_ID,
      question: REPLIT_QUESTION,
    });

    if (result.isError === true) {
      return {
        asked: false,
        reason: "error",
        detail: result.content.map((part) => (part.type === "text" ? part.text : `<${part.type}>`)).join(" ").slice(0, 300),
      };
    }

    await input.kv.put(key, { at: Date.now(), askedAt: Date.now() } satisfies AskRecord);

    const text = result.content
      .map((part) => (part.type === "text" ? part.text : `<${part.type}>`))
      .join(" ")
      .slice(0, 500);
    return { asked: true, text };
  } catch (error) {
    return {
      asked: false,
      reason: "error",
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}
