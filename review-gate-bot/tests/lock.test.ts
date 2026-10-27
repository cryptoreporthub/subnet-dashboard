import assert from "node:assert/strict";
import test from "node:test";
import { createMemoryKv, type HostKvApi } from "@grok/agent-sdk/kv";
import { LEASE_MS, ranOnce } from "../bot/lib/lock.js";

/** A plain kv that exposes only get/put/delete — the documented surface. */
function plainKv(): HostKvApi & { store: Map<string, unknown> } {
  const store = new Map<string, unknown>();
  return {
    store,
    async get(key) {
      return store.get(key) as never;
    },
    async put(key, value) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

test("runs the effect when the system of record says it has not happened", async () => {
  const kv = plainKv();
  let ran = 0;
  const result = await ranOnce({
    kv,
    key: "tag:1:abc",
    alreadyDone: async () => false,
    run: async () => {
      ran += 1;
    },
  });
  assert.equal(result.ran, true);
  assert.equal(ran, 1);
});

test("does not run when the effect is already visible, even with no kv record", async () => {
  const kv = plainKv();
  let ran = 0;
  const result = await ranOnce({
    kv,
    key: "tag:1:abc",
    alreadyDone: async () => true,
    run: async () => {
      ran += 1;
    },
  });
  assert.equal(result.ran, false);
  assert.equal(result.reason, "already-done");
  assert.equal(ran, 0);
});

test("a second call after a successful run does not repeat the effect", async () => {
  const kv = plainKv();
  let posted = 0;
  const alreadyDone = async () => posted > 0;
  const run = async () => {
    posted += 1;
  };
  await ranOnce({ kv, key: "tag:1:abc", alreadyDone, run });
  const second = await ranOnce({ kv, key: "tag:1:abc", alreadyDone, run });
  assert.equal(second.ran, false);
  assert.equal(posted, 1);
});

test("a throw releases the claim so a retry can run", async () => {
  const kv = plainKv();
  await assert.rejects(
    ranOnce({
      kv,
      key: "tag:1:abc",
      alreadyDone: async () => false,
      run: async () => {
        throw new Error("github 502");
      },
    }),
  );
  assert.equal(kv.store.has("tag:1:abc"), false);

  let ran = 0;
  const retry = await ranOnce({
    kv,
    key: "tag:1:abc",
    alreadyDone: async () => false,
    run: async () => {
      ran += 1;
    },
  });
  assert.equal(retry.ran, true);
  assert.equal(ran, 1);
});

test("a duplicate delivery is caught by the system of record, not the kv claim", async () => {
  const kv = plainKv();
  let posted = 0;
  // `alreadyDone` only becomes true once the post has landed, which is what a
  // real GitHub read does. Both callers may pass the first check; the marker is
  // what makes the second one harmless.
  const alreadyDone = async () => posted > 0;
  const run = async () => {
    posted += 1;
  };

  const [a, b] = await Promise.all([
    ranOnce({ kv, key: "tag:1:abc", alreadyDone, run }),
    ranOnce({ kv, key: "tag:1:abc", alreadyDone, run }),
  ]);

  // Two handlers in one process are serialised per key, so the second always
  // finds the first one's post.
  assert.equal(posted, 1, "exactly one post");
  const replay = await ranOnce({ kv, key: "tag:1:abc", alreadyDone, run });
  assert.equal(replay.ran, false);
  assert.equal(replay.reason, "already-done");
  assert.equal(a.ran !== b.ran, true, "exactly one of the two ran it");
});

// --- Concurrency, crash recovery, and a failing bookkeeping write ----------

/** Yield a random number of event-loop turns, so handlers interleave differently every trial. */
const tick = async (): Promise<void> => {
  for (let turns = Math.floor(Math.random() * 4); turns >= 0; turns -= 1) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
};

/** A plain kv whose every call yields, so interleavings actually happen. */
function yieldingKv(): HostKvApi & { store: Map<string, unknown> } {
  const inner = plainKv();
  return {
    store: inner.store,
    async get(key) {
      await tick();
      return inner.get(key);
    },
    async put(key, value) {
      await tick();
      await inner.put(key, value);
    },
    async delete(key) {
      await tick();
      await inner.delete(key);
    },
  };
}

for (const handlers of [2, 3, 5, 8]) {
  test(`${handlers} concurrent handlers for one key post exactly once, every time`, async () => {
    for (let trial = 0; trial < 40; trial += 1) {
      const kv = yieldingKv();
      const posts: number[] = [];
      // GitHub: the read sees a post only after it has landed.
      const alreadyDone = async () => {
        await tick();
        return posts.length > 0;
      };
      const run = async () => {
        await tick();
        posts.push(posts.length);
      };
      const results = await Promise.all(
        Array.from({ length: handlers }, () => ranOnce({ kv, key: "tag:7:abc", alreadyDone, run })),
      );
      assert.equal(posts.length, 1, `trial ${trial}: posted ${posts.length} times`);
      assert.equal(results.filter((r) => r.ran).length, 1);
    }
  });
}

test("different keys do not wait on each other", async () => {
  const kv = yieldingKv();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const slow = ranOnce({ kv, key: "tag:7:slow", alreadyDone: async () => false, run: () => gate });
  const fast = await ranOnce({ kv, key: "tag:7:fast", alreadyDone: async () => false, run: async () => {} });
  assert.equal(fast.ran, true, "the other key finished while this one was still running");
  release();
  assert.equal((await slow).ran, true);
});

test("a claim held by a live owner is respected, even without compare-and-swap", async () => {
  const kv = plainKv();
  const now = 1_000_000;
  kv.store.set("tag:1:abc", { state: "claimed", nonce: "other-process", at: now - 5_000 });
  let ran = 0;
  const result = await ranOnce({
    kv,
    key: "tag:1:abc",
    alreadyDone: async () => false,
    run: async () => {
      ran += 1;
    },
    now: () => now,
  });
  assert.equal(result.ran, false);
  assert.equal(result.reason, "claim-lost");
  assert.equal(ran, 0);
});

for (const [label, makeKv] of [
  ["plain kv", () => plainKv() as HostKvApi & { store?: Map<string, unknown> }],
  ["compare-and-swap kv", () => createMemoryKv() as HostKvApi],
] as const) {
  test(`a claim whose owner died is taken over after the lease (${label})`, async () => {
    const kv = makeKv();
    const now = 10_000_000;
    await kv.put("tag:1:abc", { state: "claimed", nonce: "crashed", at: now - LEASE_MS - 1 });
    let ran = 0;
    const result = await ranOnce({
      kv,
      key: "tag:1:abc",
      alreadyDone: async () => false,
      run: async () => {
        ran += 1;
      },
      now: () => now,
    });
    assert.equal(result.ran, true, "the stale claim must not block the retry for ever");
    assert.equal(ran, 1);
  });
}

test("a failed bookkeeping write after the effect landed is not an error", async () => {
  const kv = plainKv();
  const realPut = kv.put.bind(kv);
  kv.put = async (key, value) => {
    if ((value as { state?: string }).state === "done") {
      throw new Error("kv 503");
    }
    await realPut(key, value);
  };
  let ran = 0;
  const result = await ranOnce({
    kv,
    key: "tag:1:abc",
    alreadyDone: async () => ran > 0,
    run: async () => {
      ran += 1;
    },
  });
  assert.equal(result.ran, true, "the comment is posted; GitHub is the record");
  const replay = await ranOnce({ kv, key: "tag:1:abc", alreadyDone: async () => ran > 0, run: async () => {} });
  assert.equal(replay.reason, "already-done");
});
