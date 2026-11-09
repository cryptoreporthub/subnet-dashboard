import { randomUUID } from "node:crypto";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import { supportsKvCas } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { replitAskKey, replitAskLeaseKey } from "./gate.js";
import {
  askDiscoveryBudgetMs,
  exclusive,
  leaseRenewIntervalMs,
  leaseToken,
  releaseLeaseIfHolder,
  renewLeaseIfHolder,
} from "./lock.js";
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
 * Reclaim `inFlightAt` after a crash before `callTool`. Matches the gate lease
 * order of magnitude and is renewed while `callTool` is pending.
 */
export const IN_FLIGHT_LEASE_MS = 15 * 60_000;

export const IN_FLIGHT_RENEW_MS = Math.floor(IN_FLIGHT_LEASE_MS / 3);

export type ReplitAskFailure = "unavailable" | "no-tool" | "error";

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
  /** MCP returned OK but `askedAt` may not have persisted — still no second ask. */
  deliveredAt?: number;
  /** Claim before `callTool`; suppresses overlap until lease expires or delivery is recorded. */
  inFlightAt?: number;
  /** Owning attempt for in-flight writes across processes. */
  claimNonce?: string;
  /** Failed attempts, so a retry is bounded and a persistent failure is visible. */
  failedAttempts?: number;
  lastFailure?: string;
  at: number;
};

/** Tests pin a shorter lease without affecting production defaults. */
let testInFlightLeaseMs: number | undefined;
let testRenewInFlightDuringCall = true;

export function __testOnly_setInFlightLeaseMs(ms: number | undefined): void {
  testInFlightLeaseMs = ms;
}

export function __testOnly_setRenewInFlightDuringCall(enabled: boolean): void {
  testRenewInFlightDuringCall = enabled;
}

/** Cross-process tests: attempt an owner failure write without a live ask. */
export async function __testOnly_ownerFailureWrite(
  kv: HostKvApi,
  ref: PrRef,
  headSha: string,
  ownerClaimNonce: string,
  failedAttempts: number,
): Promise<boolean> {
  const key = replitAskKey(ref, headSha);
  const now = Date.now();
  return putRecordUnlessSuperseded(
    kv,
    key,
    ownerClaimNonce,
    {
      at: now,
      failedAttempts,
      lastFailure: "error: stale",
      claimNonce: ownerClaimNonce,
    } satisfies AskRecord,
    "owner",
  );
}

function inFlightLeaseMs(): number {
  return testInFlightLeaseMs ?? IN_FLIGHT_LEASE_MS;
}

function terminalAskRecorded(record: AskRecord): boolean {
  return record.askedAt !== undefined || record.deliveredAt !== undefined;
}

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

export function askAlreadySent(record: AskRecord, now = Date.now()): boolean {
  if (terminalAskRecorded(record)) {
    return true;
  }
  if (record.inFlightAt === undefined) {
    return false;
  }
  return now - record.inFlightAt < inFlightLeaseMs();
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

type DiscoveryOutcome =
  | { kind: "ready"; available: boolean }
  | { kind: "timeout"; pending: Promise<boolean> };

async function awaitDiscovery(
  mcp: HostMcpRegistry,
  budgetMs: number | undefined,
): Promise<DiscoveryOutcome> {
  const discovery = replitAvailable(mcp);
  if (budgetMs === undefined) {
    return { kind: "ready", available: await discovery };
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<{ kind: "timeout" }>((resolve) => {
    timer = setTimeout(() => resolve({ kind: "timeout" }), budgetMs);
  });
  try {
    const raced = await Promise.race([
      discovery.then((available) => ({ kind: "ready" as const, available })),
      deadline,
    ]);
    if (raced.kind === "timeout") {
      return { kind: "timeout", pending: discovery };
    }
    return raced;
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

function casKvReady(kv: HostKvApi): boolean {
  const cas = kv as HostKvApi & {
    getWithVersion?: (key: string) => Promise<{ value: unknown; version: string } | undefined>;
    putIfVersion?: (key: string, value: unknown, version: string) => Promise<{ ok: boolean }>;
    putIfAbsent?: (key: string, value: unknown) => Promise<{ ok: boolean; current?: { value: unknown; version: string } }>;
  };
  return typeof cas.getWithVersion === "function" && typeof cas.putIfVersion === "function";
}

/**
 * CAS insert or update. Absent keys require `putIfAbsent`; otherwise fail closed
 * so a concurrent successful ask cannot be erased by an unconditional put.
 */
async function casWriteRecord(
  kv: HostKvApi,
  key: string,
  next: AskRecord,
  rejectLive: (live: AskRecord) => boolean,
): Promise<boolean> {
  if (!casKvReady(kv)) {
    return false;
  }
  const cas = kv as HostKvApi & {
    getWithVersion: (key: string) => Promise<{ value: unknown; version: string } | undefined>;
    putIfVersion: (key: string, value: unknown, version: string) => Promise<{ ok: boolean }>;
    putIfAbsent?: (key: string, value: unknown) => Promise<{ ok: boolean; current?: { value: unknown; version: string } }>;
  };
  try {
    const current = await cas.getWithVersion(key);
    const live = asAskRecord(current?.value);
    if (live !== undefined && rejectLive(live)) {
      return false;
    }
    if (current === undefined) {
      if (typeof cas.putIfAbsent !== "function") {
        return false;
      }
      const created = await cas.putIfAbsent(key, next);
      if (created.ok) {
        return true;
      }
      const raced = asAskRecord(created.current?.value);
      if (raced !== undefined && rejectLive(raced)) {
        return false;
      }
      if (created.current !== undefined) {
        return (await cas.putIfVersion(key, next, created.current.version)).ok;
      }
      return false;
    }
    return (await cas.putIfVersion(key, next, current.version)).ok;
  } catch {
    return false;
  }
}

async function putFailureUnlessTerminal(kv: HostKvApi, key: string, next: AskRecord): Promise<boolean> {
  if (casKvReady(kv)) {
    return casWriteRecord(kv, key, next, (live) => terminalAskRecorded(live) || askAlreadySent(live));
  }

  const read = asAskRecord(await kv.get(key));
  if (read !== undefined && terminalAskRecorded(read)) {
    return false;
  }
  if (read !== undefined && askAlreadySent(read)) {
    return false;
  }
  try {
    await kv.put(key, next);
    return true;
  } catch {
    return false;
  }
}

type PutRecordMode = "acquire" | "owner";

/** Whether a new claim must wait (active in-flight lease or terminal success). */
function blocksNewClaim(record: AskRecord, claimNonce: string, now = Date.now()): boolean {
  if (terminalAskRecorded(record)) {
    return true;
  }
  if (record.claimNonce === undefined || record.claimNonce === claimNonce) {
    return false;
  }
  if (record.inFlightAt === undefined) {
    return false;
  }
  return now - record.inFlightAt < inFlightLeaseMs();
}

/** Whether an in-flight owner write is stale relative to the stored record. */
function blocksOwnerWrite(record: AskRecord, ownerClaimNonce: string, next: AskRecord): boolean {
  if (record.claimNonce !== undefined && record.claimNonce !== ownerClaimNonce) {
    return true;
  }
  if (terminalAskRecorded(record) && !terminalAskRecorded(next)) {
    return true;
  }
  return false;
}

function blocksWrite(
  record: AskRecord,
  claimNonce: string,
  mode: PutRecordMode,
  next: AskRecord,
  now = Date.now(),
): boolean {
  if (mode === "owner") {
    return blocksOwnerWrite(record, claimNonce, next);
  }
  return blocksNewClaim(record, claimNonce, now);
}

async function putRecordUnlessSuperseded(
  kv: HostKvApi,
  key: string,
  claimNonce: string,
  next: AskRecord,
  mode: PutRecordMode,
): Promise<boolean> {
  const read = asAskRecord(await kv.get(key));
  if (read !== undefined && blocksWrite(read, claimNonce, mode, next)) {
    return false;
  }

  if (casKvReady(kv)) {
    return casWriteRecord(kv, key, next, (live) => blocksWrite(live, claimNonce, mode, next));
  }

  try {
    await kv.put(key, next);
    return true;
  } catch {
    return false;
  }
}

async function renewInFlightLease(kv: HostKvApi, key: string, claimNonce: string): Promise<void> {
  try {
    const current = asAskRecord(await kv.get(key));
    if (current === undefined || current.claimNonce !== claimNonce) {
      return;
    }
    if (terminalAskRecorded(current)) {
      return;
    }
    if (current.inFlightAt === undefined) {
      return;
    }
    const now = Date.now();
    await putRecordUnlessSuperseded(kv, key, claimNonce, { ...current, at: now, inFlightAt: now, claimNonce }, "owner");
  } catch {
    // Best-effort: a transient KV error must not escape the timer callback.
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
async function askReplitOnceWithLease(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  const key = replitAskKey(input.ref, input.headSha);
  const leaseKey = replitAskLeaseKey(input.ref, input.headSha);
  const token = await leaseToken(input.kv, leaseKey);
  if (token === undefined) {
    const previous = asAskRecord(await input.kv.get(key));
    if (previous !== undefined && askAlreadySent(previous)) {
      return {
        asked: false,
        reason: "already-asked",
        detail:
          terminalAskRecorded(previous) ? "recorded for this head" : "ask in flight for this head",
      };
    }
    return {
      asked: false,
      reason: "already-asked",
      detail: "another handler holds the replit ask lease",
    };
  }
  const renewMs = leaseRenewIntervalMs();
  let renewTimer: ReturnType<typeof setInterval> | undefined;
  if (supportsKvCas(input.kv)) {
    renewTimer = setInterval(() => {
      void renewLeaseIfHolder(input.kv, leaseKey, token).catch(() => undefined);
    }, renewMs);
  }
  const discoveryBudget = supportsKvCas(input.kv) ? undefined : askDiscoveryBudgetMs();
  let discoveryDrain: Promise<unknown> | undefined;
  try {
    return await askReplit({
      ...input,
      maxDiscoveryMs: discoveryBudget,
      onDiscoveryTimeout(pending) {
        discoveryDrain = pending.catch(() => undefined);
      },
    });
  } finally {
    if (renewTimer !== undefined) {
      clearInterval(renewTimer);
      renewTimer = undefined;
    }
    if (discoveryDrain !== undefined) {
      await discoveryDrain;
    }
    await releaseLeaseIfHolder(input.kv, leaseKey, token).catch(() => undefined);
  }
}

export function askReplitOnce(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  // In-process queue plus a KV lease: `exclusive` alone does not span hosted processes.
  return exclusive(replitAskKey(input.ref, input.headSha), () => askReplitOnceWithLease(input));
}

/** Parallel tests simulate another process without the in-process `exclusive` queue. */
export function __testOnly_askReplitOnceCrossProcess(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  return askReplitOnceWithLease(input);
}

/** Parallel cross-process tests call the same path without the process-local queue. */
export function __testOnly_askReplit(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
}): Promise<ReplitAskOutcome> {
  return askReplit(input);
}

async function askReplit(input: {
  kv: HostKvApi;
  mcp: HostMcpRegistry;
  ref: PrRef;
  headSha: string;
  /** When set, bound MCP discovery so plain-KV leases are not outlived. */
  maxDiscoveryMs?: number;
  /** Called when discovery hits the budget; caller must await before releasing a plain-KV lease. */
  onDiscoveryTimeout?: (pending: Promise<boolean>) => void;
}): Promise<ReplitAskOutcome> {
  const key = replitAskKey(input.ref, input.headSha);
  const previous = asAskRecord(await input.kv.get(key));

  if (previous !== undefined && askAlreadySent(previous)) {
    return {
      asked: false,
      reason: "already-asked",
      detail:
        terminalAskRecorded(previous) ? "recorded for this head" : "ask in flight for this head",
    };
  }

  const failedAttempts = previous?.failedAttempts ?? 0;
  if (failedAttempts >= ASK_ATTEMPTS) {
    return {
      asked: false,
      reason: "error",
      detail: `gave up after ${failedAttempts} attempts: ${previous?.lastFailure ?? "unknown"}`,
      attempts: failedAttempts,
      persistent: true,
    };
  }

  const recordFailure = async (
    reason: ReplitAskFailure,
    rawDetail: string,
    ownerNonce: string | undefined,
  ): Promise<ReplitAskOutcome> => {
    const detail = redactSecrets(rawDetail).text;
    const attempts = failedAttempts + 1;
    const now = Date.now();
    const failureRecord = {
      at: now,
      failedAttempts: attempts,
      lastFailure: `${reason}: ${detail}`.slice(0, 300),
      ...(ownerNonce === undefined ? {} : { claimNonce: ownerNonce }),
    } satisfies AskRecord;
    const wrote =
      ownerNonce === undefined
        ? await putFailureUnlessTerminal(input.kv, key, failureRecord)
        : await putRecordUnlessSuperseded(input.kv, key, ownerNonce, failureRecord, "owner");
    if (!wrote) {
      const current = asAskRecord(await input.kv.get(key));
      if (current !== undefined && (terminalAskRecorded(current) || askAlreadySent(current))) {
        return { asked: false, reason: "already-asked", detail: "recorded for this head" };
      }
      return {
        asked: false,
        reason: "error",
        detail: "superseded by a newer ask attempt",
        attempts,
        persistent: false,
      };
    }
    return { asked: false, reason, detail, attempts, persistent: attempts >= ASK_ATTEMPTS };
  };

  const discovery = await awaitDiscovery(input.mcp, input.maxDiscoveryMs);
  if (discovery.kind === "timeout") {
    input.onDiscoveryTimeout?.(discovery.pending);
    return recordFailure("unavailable", `replit discovery timed out after ${input.maxDiscoveryMs}ms`, undefined);
  }
  if (!discovery.available) {
    return recordFailure("unavailable", `no ${REPLIT_TOOL} on the "${REPLIT_CONNECTION}" connection`, undefined);
  }

  const claimNonce = randomUUID();
  const claimTime = Date.now();
  const claimed = await putRecordUnlessSuperseded(input.kv, key, claimNonce, {
    at: claimTime,
    inFlightAt: claimTime,
    claimNonce,
    failedAttempts: failedAttempts > 0 ? failedAttempts : undefined,
  } satisfies AskRecord, "acquire");
  if (!claimed) {
    return { asked: false, reason: "already-asked", detail: "ask in flight for this head" };
  }

  const renewMs = Math.max(50, Math.floor(inFlightLeaseMs() / 3));
  let renewTimer: ReturnType<typeof setInterval> | undefined;
  if (testRenewInFlightDuringCall) {
    renewTimer = setInterval(() => {
      void renewInFlightLease(input.kv, key, claimNonce).catch(() => {});
    }, renewMs);
  }

  try {
    const result = await input.mcp.callTool(REPLIT_CONNECTION, REPLIT_TOOL, {
      replId: REPL_ID,
      question: replitQuestion(input.ref.number, input.headSha),
    });

    if (result.isError === true) {
      const detail = result.content
        .map((part) => (part.type === "text" ? part.text : `<${part.type}>`))
        .join(" ")
        .slice(0, 300);
      return recordFailure("error", detail, claimNonce);
    }

    const text = result.content
      .map((part) => (part.type === "text" ? part.text : `<${part.type}>`))
      .join(" ")
      .slice(0, 500);

    const now = Date.now();
    const wrote = await putRecordUnlessSuperseded(input.kv, key, claimNonce, {
      at: now,
      askedAt: now,
      inFlightAt: now,
      claimNonce,
    } satisfies AskRecord, "owner");
    if (!wrote) {
      const current = asAskRecord(await input.kv.get(key));
      if (current !== undefined && terminalAskRecorded(current)) {
        return { asked: false, reason: "already-asked", detail: "recorded for this head" };
      }
      await putRecordUnlessSuperseded(input.kv, key, claimNonce, {
        at: now,
        deliveredAt: now,
        inFlightAt: now,
        claimNonce,
      } satisfies AskRecord, "owner");
    }

    return { asked: true, text, attempts: failedAttempts + 1 };
  } catch (error) {
    return recordFailure("error", error instanceof Error ? error.message : String(error), claimNonce);
  } finally {
    if (renewTimer !== undefined) {
      clearInterval(renewTimer);
    }
  }
}
