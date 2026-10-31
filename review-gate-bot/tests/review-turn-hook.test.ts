import assert from "node:assert/strict";
import test from "node:test";
import hook from "../bot/hooks/review-turn.js";
import { reviewTurnKey } from "../bot/lib/gate.js";

const HEAD = "a".repeat(40);
const TOKEN = "lease-token-1";
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const KEY = "cont:github-pr:cryptoreporthub/subnet-dashboard#1522";

function kv() {
  const store = new Map<string, unknown>();
  return {
    store,
    async get(key: string) {
      return store.get(key);
    },
    async put(key: string, value: unknown) {
      store.set(key, value);
    },
    async delete(key: string) {
      store.delete(key);
    },
  };
}

type Events = Record<string, (event: { data: { status?: string } }, ctx: unknown) => Promise<void>>;

test("a review turn that completes without a verdict releases its own lease at once, not at the TTL", async () => {
  const store = kv();
  await store.put(reviewTurnKey(REF, HEAD), { state: "claimed", nonce: TOKEN, at: Date.now() });
  const ctx = {
    session: { purpose: "live", continuationKey: KEY },
    channelState: { reviewLease: { head: HEAD, token: TOKEN } },
    host: { kv: store },
  };
  await (hook as unknown as { events: Events }).events["turn.completed"]!({ data: {} }, ctx);
  assert.equal(store.store.has(reviewTurnKey(REF, HEAD)), false, "the lease is released, so the next delivery may start a turn");
});

test("a completed turn does not release a lease that belongs to another turn", async () => {
  const store = kv();
  await store.put(reviewTurnKey(REF, HEAD), { state: "claimed", nonce: "someone-else", at: Date.now() });
  const ctx = {
    session: { purpose: "live", continuationKey: KEY },
    channelState: { reviewLease: { head: HEAD, token: TOKEN } },
    host: { kv: store },
  };
  await (hook as unknown as { events: Events }).events["turn.completed"]!({ data: {} }, ctx);
  assert.ok(store.store.has(reviewTurnKey(REF, HEAD)), "a replacement turn's lease survives");
});
