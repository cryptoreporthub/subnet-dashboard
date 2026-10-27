import type { HostKvApi } from "@grok/agent-sdk/kv";
import { supportsKvCas } from "@grok/agent-sdk";

/**
 * One-shot guard for a side effect that should happen once per
 * `(PR, head SHA)`.
 *
 * The kv store behind `ctx.host.kv` is documented as plain `get` / `put` /
 * `delete`: no compare-and-swap. `supportsKvCas` + `putIfAbsent` is used when
 * the store exposes the CAS superset, which narrows the race, but a store
 * without it does a last-writer-wins `put` and a read-back, and both writers can
 * read their own nonce.
 *
 * **So the guarantee is "at most once, best effort".** It used to be documented
 * as "a lost race costs at worst a duplicate read, never a duplicate post",
 * which was not true: `alreadyDone()` followed by `post` is a read-then-write,
 * and two turns can both pass the read.
 *
 * What actually makes a duplicate harmless is the destination, not this module:
 * every comment carries a marker, and the gate reads the first marker it finds.
 * So the honest claim is:
 *
 * - **Replays and duplicate deliveries never double-post** — `alreadyDone()`
 *   sees the first one.
 * - **A genuine simultaneous race can.** Two comments, same content, same
 *   marker; the gate is unaffected.
 *
 * Callers that must not double-post re-read immediately before posting
 * (`postVerdictComment` does), which shrinks the window without closing it.
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
  /** Stable key, e.g. `tag:1515:<sha>:cursor-ditto`. */
  key: string;
  /** Is the effect already visible in the system of record? Authoritative. */
  alreadyDone: () => Promise<boolean>;
  /** Perform the effect. Throwing releases the claim so a retry can run. */
  run: () => Promise<void>;
  /** The clock, for tests. */
  now?: () => number;
};

function nonce(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

type ClaimRecord = {
  state: "claimed" | "done";
  nonce: string;
  at: number;
};

function asClaim(value: unknown): ClaimRecord | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  const record = value as Partial<ClaimRecord>;
  if (
    (record.state !== "claimed" && record.state !== "done") ||
    typeof record.nonce !== "string" ||
    typeof record.at !== "number"
  ) {
    return undefined;
  }
  return { state: record.state, nonce: record.nonce, at: record.at };
}

/**
 * Claim the key, returning true when this caller may run.
 *
 * With CAS the claim is atomic. Without it, the write is a last-writer-wins
 * `put` followed by a read-back: a caller that finds its own nonce proceeds,
 * but both writers can. That is why the module's guarantee is "at most once,
 * best effort" and why `alreadyDone()` decides on replays.
 */
async function claim(kv: HostKvApi, key: string, token: string): Promise<boolean> {
  const record: ClaimRecord = { state: "claimed", nonce: token, at: Date.now() };
  if (supportsKvCas(kv)) {
    const result = await kv.putIfAbsent(key, record);
    if (result.ok) {
      return true;
    }
    const existing = asClaim(result.current?.value);
    return existing?.nonce === token;
  }
  await kv.put(key, record);
  const readBack = asClaim(await kv.get(key));
  return readBack?.nonce === token;
}

async function release(kv: HostKvApi, key: string, token: string): Promise<void> {
  const current = asClaim(await kv.get(key));
  if (current?.nonce === token && current.state === "claimed") {
    await kv.delete(key);
  }
}

export async function ranOnce(input: RanOnceInput): Promise<RanOnceResult> {
  // 1. The system of record decides. This is what makes a replay safe.
  if (await input.alreadyDone()) {
    await input.kv.put(input.key, { state: "done", nonce: nonce(), at: Date.now() } satisfies ClaimRecord);
    return { ran: false, reason: "already-done" };
  }

  const token = nonce();
  const won = await claim(input.kv, input.key, token);

  if (!won) {
    // Another writer may have finished between our check and its post.
    if (await input.alreadyDone()) {
      return { ran: false, reason: "already-done" };
    }
    return { ran: false, reason: "claim-lost" };
  }

  try {
    await input.run();
  } catch (error) {
    await release(input.kv, input.key, token);
    throw error;
  }

  await input.kv.put(input.key, { state: "done", nonce: token, at: Date.now() } satisfies ClaimRecord);
  return { ran: true, reason: "ran" };
}
