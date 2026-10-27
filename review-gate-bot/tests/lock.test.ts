import assert from "node:assert/strict";
import test from "node:test";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { ranOnce } from "../bot/lib/lock.js";

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

  // The honest guarantee: a genuine simultaneous race can post twice, and the
  // gate reads the first marker. What must not happen is a replay (a delivery
  // after the post) running again.
  const replay = await ranOnce({ kv, key: "tag:1:abc", alreadyDone, run });
  assert.equal(replay.ran, false);
  assert.equal(replay.reason, "already-done");
  assert.ok(posted >= 1, "at least one post happened");
  assert.equal(a.ran || b.ran || replay.ran, true);
});
