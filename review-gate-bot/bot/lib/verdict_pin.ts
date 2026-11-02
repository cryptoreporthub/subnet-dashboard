import { createHash } from "node:crypto";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { PrRef } from "./gh.js";
import type { CommentLike, ReviewerName, Verdict } from "./verdicts.js";

/** What the gate recorded the first time it trusted this comment id. */
export type VerdictFirstSeen = {
  verdict: Verdict;
  headSha: string;
  bodyHash: string;
  recordedAt: string;
  /** Latest FAIL/MODIFY seen on an edit at the same head as firstSeen (blocks PASS re-edit). */
  lastNonPassVerdict?: Verdict;
  lastNonPassHeadSha?: string;
};

export function commentBodyHash(body: string): string {
  return createHash("sha256").update(body).digest("hex");
}

export function verdictPinKey(ref: PrRef, slot: ReviewerName, commentId: number): string {
  return `review-gate:verdict-pin:v1:${ref.owner}/${ref.repo}#${ref.number}:${slot}:${commentId}`;
}

export interface VerdictPinStore {
  get(key: string): VerdictFirstSeen | undefined;
  put(key: string, value: VerdictFirstSeen): void;
  /** Set when hydrate could not read this key from kv (resolve fail-closed for PASS). */
  noteHydrateGetFailed?(key: string): void;
  hydrateGetFailed?(key: string): boolean;
}

export class MemoryVerdictPinStore implements VerdictPinStore {
  private readonly map = new Map<string, VerdictFirstSeen>();
  private readonly hydrateFailed = new Set<string>();

  get(key: string): VerdictFirstSeen | undefined {
    return this.map.get(key);
  }

  put(key: string, value: VerdictFirstSeen): void {
    this.map.set(key, value);
  }

  noteHydrateGetFailed(key: string): void {
    this.hydrateFailed.add(key);
  }

  hydrateGetFailed(key: string): boolean {
    return this.hydrateFailed.has(key);
  }

  entries(): Iterable<[string, VerdictFirstSeen]> {
    return this.map.entries();
  }
}

export type PinOutcome =
  | { kind: "pin"; verdict: Verdict; headSha: string }
  | { kind: "drop" }
  | { kind: "kv-fail-closed" };

function isEditedByTimestamp(comment: CommentLike): boolean {
  if (comment.updatedAt === undefined) {
    return false;
  }
  const created = Date.parse(comment.createdAt);
  const updated = Date.parse(comment.updatedAt);
  return !Number.isNaN(created) && !Number.isNaN(updated) && updated > created;
}

function tryPut(store: VerdictPinStore, key: string, record: VerdictFirstSeen, parsedVerdict: Verdict): boolean {
  try {
    store.put(key, record);
    return true;
  } catch {
    return parsedVerdict !== "PASS";
  }
}

function pinnedFromStored(stored: VerdictFirstSeen): { verdict: Verdict; headSha: string } {
  if (stored.lastNonPassVerdict !== undefined && stored.lastNonPassHeadSha === stored.headSha) {
    return { verdict: stored.lastNonPassVerdict, headSha: stored.lastNonPassHeadSha };
  }
  return { verdict: stored.verdict, headSha: stored.headSha };
}

function recordLastNonPass(stored: VerdictFirstSeen, parsedVerdict: Verdict, parsedHeadSha: string, hash: string): VerdictFirstSeen {
  if (parsedHeadSha !== stored.headSha) {
    return { ...stored, bodyHash: hash };
  }
  return {
    ...stored,
    bodyHash: hash,
    lastNonPassVerdict: parsedVerdict,
    lastNonPassHeadSha: parsedHeadSha,
  };
}

/**
 * Apply r18 edit + firstSeen policy for one pinned comment (all reviewer slots).
 */
export function resolveCommentVerdictPin(input: {
  store: VerdictPinStore;
  ref: PrRef;
  slot: ReviewerName;
  comment: CommentLike;
  parsedVerdict: Verdict | undefined;
  parsedHeadSha: string;
}): PinOutcome {
  const { store, ref, slot, comment, parsedHeadSha } = input;
  const key = verdictPinKey(ref, slot, comment.id);
  const hash = commentBodyHash(comment.body);
  const editedByTime = isEditedByTimestamp(comment);

  if (store.hydrateGetFailed?.(key)) {
    if (input.parsedVerdict === "PASS" || input.parsedVerdict === undefined) {
      return { kind: "kv-fail-closed" };
    }
  }

  let stored: VerdictFirstSeen | undefined;
  try {
    stored = store.get(key);
  } catch {
    if (input.parsedVerdict === "PASS" || input.parsedVerdict === undefined) {
      return { kind: "kv-fail-closed" };
    }
    return { kind: "pin", verdict: input.parsedVerdict, headSha: parsedHeadSha };
  }

  const parsedVerdict = input.parsedVerdict;

  if (parsedVerdict === undefined) {
    if (stored !== undefined) {
      const pin = pinnedFromStored(stored);
      return { kind: "pin", verdict: pin.verdict, headSha: pin.headSha };
    }
    return { kind: "drop" };
  }

  if (stored === undefined && editedByTime && parsedVerdict === "PASS") {
    return { kind: "drop" };
  }

  const editedByHash = stored !== undefined && stored.bodyHash !== hash;
  const treatAsEdited = editedByTime || editedByHash;

  if (stored === undefined && !treatAsEdited) {
    const record: VerdictFirstSeen = {
      verdict: parsedVerdict,
      headSha: parsedHeadSha,
      bodyHash: hash,
      recordedAt: comment.createdAt,
    };
    if (!tryPut(store, key, record, parsedVerdict)) {
      return { kind: "kv-fail-closed" };
    }
    return { kind: "pin", verdict: parsedVerdict, headSha: parsedHeadSha };
  }

  if (stored === undefined && treatAsEdited && parsedVerdict !== "PASS") {
    const record: VerdictFirstSeen = {
      verdict: parsedVerdict,
      headSha: parsedHeadSha,
      bodyHash: hash,
      recordedAt: comment.createdAt,
    };
    tryPut(store, key, record, parsedVerdict);
    return { kind: "pin", verdict: parsedVerdict, headSha: parsedHeadSha };
  }

  if (stored === undefined) {
    return { kind: "drop" };
  }

  if (treatAsEdited) {
    if (parsedHeadSha !== stored.headSha) {
      return { kind: "pin", verdict: stored.verdict, headSha: stored.headSha };
    }
    if (parsedVerdict === "PASS") {
      const pin = pinnedFromStored(stored);
      return { kind: "pin", verdict: pin.verdict, headSha: pin.headSha };
    }
    const updated = recordLastNonPass(stored, parsedVerdict, parsedHeadSha, hash);
    tryPut(store, key, updated, parsedVerdict);
    return { kind: "pin", verdict: parsedVerdict, headSha: parsedHeadSha };
  }

  if (hash !== stored.bodyHash) {
    const record: VerdictFirstSeen = {
      verdict: parsedVerdict,
      headSha: parsedHeadSha,
      bodyHash: hash,
      recordedAt: stored.recordedAt,
    };
    if (!tryPut(store, key, record, parsedVerdict)) {
      return { kind: "kv-fail-closed" };
    }
  }

  return { kind: "pin", verdict: parsedVerdict, headSha: parsedHeadSha };
}

export async function hydrateVerdictPinsFromKv(input: {
  kv: HostKvApi;
  ref: PrRef;
  comments: readonly CommentLike[];
  store: MemoryVerdictPinStore;
}): Promise<void> {
  const slots: ReviewerName[] = ["mc", "cursor", "ditto", "replit"];
  for (const comment of input.comments) {
    for (const slot of slots) {
      const key = verdictPinKey(input.ref, slot, comment.id);
      try {
        const value = (await input.kv.get(key)) as VerdictFirstSeen | undefined;
        if (value !== undefined) {
          input.store.put(key, value);
        }
      } catch {
        input.store.noteHydrateGetFailed?.(key);
      }
    }
  }
}

export async function flushVerdictPinsToKv(input: {
  kv: HostKvApi;
  store: MemoryVerdictPinStore;
}): Promise<void> {
  for (const [key, value] of input.store.entries()) {
    try {
      await input.kv.put(key, value);
    } catch {
      // best effort; next read may re-record
    }
  }
}
