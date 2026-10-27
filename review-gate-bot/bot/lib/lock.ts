import type { HostKvApi } from "@grok/agent-sdk/kv";
import { supportsKvCas } from "@grok/agent-sdk";

/**
 * One-shot guard for a side effect that should happen once per
 * `(PR, head SHA)`.
 *
 * ## What is guaranteed, and where
 *
 * - **Inside one process: exactly once.** Callers for the same key run one at a
 *   time (`exclusive` below), so the second always runs its `alreadyDone()` after
 *   the first one's effect has landed and finds it. This is the case that
 *   matters: a webhook storm (an opened PR, then a comment, then a review in the
 *   same second) lands in one running agent.
 * - **Across processes: at most once, best effort.** `ctx.host.kv` is plain
 *   `get` / `put` / `delete`; `supportsKvCas` is false for it in the hosted
 *   runtime (measured against the SDK's `createHostKvApi`). A claim record with
 *   a lease narrows the window, and the system of record closes it for replays:
 *   every comment carries a marker, and the gate reads the latest one. A genuine
 *   simultaneous race between two processes can still post twice, with the same
 *   content and the same marker.
 * - **A dead owner does not block for ever.** A claim older than `LEASE_MS` is
 *   taken over. With compare-and-swap the takeover is conditional on the version
 *   that was read, so two takers cannot both win.
 *
 * Callers that must not double-post re-read immediately before posting
 * (`postVerdictComment` does), which shrinks the cross-process window.
 */

/** How long a claim is believed. Past this, its owner is presumed dead. */
export const LEASE_MS = 10 * 60_000;

export type RanOnceReason = "ran" | "already-done" | "claim-lost" | "failed";

export type RanOnceResult = {
  ran: boolean;
  reason: RanOnceReason;
};

export type RanOnceInput = {
  kv: HostKvApi;
  /** Stable key, e.g. `tag:cryptoreporthub/subnet-dashboard#1515:<sha>:cursor-ditto`. */
  key: string;
  /** Is the effect already visible in the system of record? Authoritative. */
  alreadyDone: () => Promise<boolean>;
  /** Perform the effect. Throwing frees the claim for a retry at once with compare-and-swap kv, and after `LEASE_MS` without it. */
  run: () => Promise<void>;
  /** The clock, for tests. */
  now?: () => number;
};

function nonce(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

type ClaimRecord = {
  state: "claimed" | "done" | "released";
  nonce: string;
  at: number;
};

function asClaim(value: unknown): ClaimRecord | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Partial<ClaimRecord>;
  if (
    (record.state !== "claimed" && record.state !== "done" && record.state !== "released") ||
    typeof record.nonce !== "string" ||
    typeof record.at !== "number"
  ) {
    return undefined;
  }
  return { state: record.state, nonce: record.nonce, at: record.at };
}

/** Is this a claim held by an owner presumed alive? */
function isLive(record: ClaimRecord | undefined, now: number): boolean {
  return record?.state === "claimed" && now - record.at < LEASE_MS;
}

/**
 * Claim the key, returning true when this caller may run.
 *
 * A live claim held by someone else loses. A `done` record, a stale claim and
 * garbage are all replaceable: `alreadyDone()` is the authority on whether the
 * effect happened, and it has just said no.
 *
 * With CAS the replacement is conditional on the version read, so exactly one
 * taker wins. Without it the write is a `put` followed by a read-back, which
 * two processes can both pass; that is the documented best-effort edge.
 */
async function claim(kv: HostKvApi, key: string, token: string, now: number): Promise<boolean> {
  const record: ClaimRecord = { state: "claimed", nonce: token, at: now };
  if (supportsKvCas(kv)) {
    const created = await kv.putIfAbsent(key, record);
    if (created.ok) {
      return true;
    }
    const existing = asClaim(created.current?.value);
    if (existing?.nonce === token) {
      return true;
    }
    if (created.current === undefined || isLive(existing, now)) {
      return false;
    }
    return (await kv.putIfVersion(key, record, created.current.version)).ok;
  }
  if (isLive(asClaim(await kv.get(key)), now)) {
    return false;
  }
  await kv.put(key, record);
  return asClaim(await kv.get(key))?.nonce === token;
}

/**
 * Give a failed claim back so a retry can run at once, but only where that can
 * be done without touching a claim that is not ours.
 *
 * With compare-and-swap the release is a conditional write of the version that
 * was read, so a takeover in between wins. The plain `get` / `put` / `delete`
 * surface has no conditional delete, so there a failed claim is left to expire
 * after `LEASE_MS`. That costs a retry up to ten minutes; deleting would risk
 * wiping a replacement owner's live claim, and correctness beats the delay.
 */
async function release(kv: HostKvApi, key: string, token: string, now: number): Promise<void> {
  if (supportsKvCas(kv)) {
    const current = await kv.getWithVersion(key);
    const claim = asClaim(current?.value);
    if (current !== undefined && claim?.nonce === token && claim.state === "claimed") {
      await kv.putIfVersion(key, { state: "released", nonce: token, at: now } satisfies ClaimRecord, current.version);
    }
  }
}

/** The tail of each key's queue. An entry lives only while a caller is in flight. */
const queues = new Map<string, Promise<unknown>>();

/** Run `body` after every earlier caller for `key` in this process has finished. */
export async function exclusive<T>(key: string, body: () => Promise<T>): Promise<T> {
  const previous = queues.get(key) ?? Promise.resolve();
  const mine = previous.then(body, body);
  queues.set(key, mine);
  try {
    return await mine;
  } finally {
    if (queues.get(key) === mine) {
      queues.delete(key);
    }
  }
}

/**
 * Take a lease on `key`: true for one caller in each `LEASE_MS` window.
 *
 * A lease gates a decision, not an effect, so there is nothing to record and
 * nothing to release. A caller that then fails leaves the key held until it
 * expires. Callers in this process queue on `exclusive`, so exactly one wins;
 * across processes it is best effort, as `ranOnce` is.
 */
export function lease(kv: HostKvApi, key: string, now: () => number = Date.now): Promise<boolean> {
  return exclusive(key, () => claim(kv, key, nonce(), now()));
}

export function ranOnce(input: RanOnceInput): Promise<RanOnceResult> {
  return exclusive(input.key, () => ranOnceExclusive(input));
}

async function ranOnceExclusive(input: RanOnceInput): Promise<RanOnceResult> {
  const now = input.now ?? Date.now;

  // 1. The system of record decides. This is what makes a replay safe.
  if (await input.alreadyDone()) {
    await remember(input.kv, input.key, nonce(), now());
    return { ran: false, reason: "already-done" };
  }

  const token = nonce();
  if (!(await claim(input.kv, input.key, token, now()))) {
    // Another process may have finished between our check and its post.
    if (await input.alreadyDone()) {
      return { ran: false, reason: "already-done" };
    }
    return { ran: false, reason: "claim-lost" };
  }

  try {
    await input.run();
  } catch (error) {
    await release(input.kv, input.key, token, now()).catch(() => undefined);
    throw error;
  }

  await remember(input.kv, input.key, token, now());
  return { ran: true, reason: "ran" };
}

/**
 * Record that the effect is done. Bookkeeping only: GitHub is the record, so a
 * failing write here must not turn a landed post into an error (the caller would
 * retry the whole turn and post again).
 */
async function remember(kv: HostKvApi, key: string, token: string, at: number): Promise<void> {
  try {
    await kv.put(key, { state: "done", nonce: token, at } satisfies ClaimRecord);
  } catch {
    // A later call finds the marker on the PR and records it then.
  }
}
