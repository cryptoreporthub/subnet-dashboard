import assert from "node:assert/strict";
import test from "node:test";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { ASK_ATTEMPTS, askReplitOnce, REPLIT_QUESTION, REPLIT_TOOL } from "../bot/lib/replit.js";
import { replitAskKey } from "../bot/lib/gate.js";

const HEAD = "c".repeat(40);

function kv(): HostKvApi & { store: Map<string, unknown> } {
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

function mcp(
  behaviour: { available?: boolean; throwOnCall?: boolean; isError?: boolean } = {},
): HostMcpRegistry & { calls: number } {
  const state = { calls: 0 };
  const registry = {
    get calls() {
      return state.calls;
    },
    names: () => (behaviour.available === false ? [] : ["replit"]),
    listTools: async () => (behaviour.available === false ? [] : [{ name: REPLIT_TOOL }]),
    callTool: async () => {
      state.calls += 1;
      if (behaviour.throwOnCall === true) {
        throw new Error("connector 502");
      }
      if (behaviour.isError === true) {
        return { isError: true, content: [{ type: "text", text: "not available" }] };
      }
      return { isError: false, content: [{ type: "text", text: "ok" }] };
    },
  };
  return registry as unknown as HostMcpRegistry & { calls: number };
}

test("a successful ask records itself and is not repeated for the same head", async () => {
  const store = kv();
  const registry = mcp();
  const first = await askReplitOnce({ kv: store, mcp: registry, prNumber: 1, headSha: HEAD });
  assert.equal(first.asked, true);
  assert.ok(store.store.has(replitAskKey(1, HEAD)));

  const second = await askReplitOnce({ kv: store, mcp: registry, prNumber: 1, headSha: HEAD });
  assert.equal(second.asked, false);
  assert.equal(second.reason, "already-asked");
  assert.equal(registry.calls, 1, "one ask, not two");
});

test("a successful ask is never a review and never touches the gate", async () => {
  // There is no `reviewed` outcome at all: the type system is the assertion.
  const outcome = await askReplitOnce({ kv: kv(), mcp: mcp(), prNumber: 1, headSha: HEAD });
  assert.equal(outcome.asked, true);
  const keys = Object.keys(outcome);
  assert.equal(keys.includes("reviewed"), false, "an ask cannot be counted as a review");
  assert.equal(keys.includes("verdict"), false);
});

test("the question sent is the literal X", () => {
  assert.equal(REPLIT_QUESTION, "X");
});

test("a failed ask is retried on the next call instead of being dropped", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  const first = await askReplitOnce({ kv: store, mcp: failing, prNumber: 1, headSha: HEAD });
  assert.equal(first.asked, false);
  assert.equal(first.reason, "error");
  if (!first.persistent) {
    assert.equal(first.attempts, 1);
  }

  // The old behaviour: nothing recorded, nothing retried, silence. Now the
  // attempt is recorded and a later call tries again.
  const retry = await askReplitOnce({ kv: store, mcp: mcp(), prNumber: 1, headSha: HEAD });
  assert.equal(retry.asked, true, "the retry must actually reach the connector");
});

test("an unavailable connector is reported as a failure, not as success", async () => {
  const outcome = await askReplitOnce({
    kv: kv(),
    mcp: mcp({ available: false }),
    prNumber: 1,
    headSha: HEAD,
  });
  assert.equal(outcome.asked, false);
  assert.equal(outcome.reason, "unavailable");
});

test("an MCP error result is a failure", async () => {
  const outcome = await askReplitOnce({
    kv: kv(),
    mcp: mcp({ isError: true }),
    prNumber: 1,
    headSha: HEAD,
  });
  assert.equal(outcome.asked, false);
  assert.equal(outcome.reason, "error");
});

test("persistent failure surfaces after the attempt budget, and then stops trying", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  let last = await askReplitOnce({ kv: store, mcp: failing, prNumber: 1, headSha: HEAD });
  for (let i = 1; i < ASK_ATTEMPTS; i += 1) {
    last = await askReplitOnce({ kv: store, mcp: failing, prNumber: 1, headSha: HEAD });
  }
  assert.equal(last.asked, false);
  if (last.asked === false && last.reason !== "already-asked") {
    assert.equal(last.persistent, true, "the failure must be marked persistent so the channel logs it");
    assert.equal(last.attempts, ASK_ATTEMPTS);
  }

  const callsAfterBudget = failing.calls;
  const after = await askReplitOnce({ kv: store, mcp: failing, prNumber: 1, headSha: HEAD });
  assert.equal(after.asked, false);
  if (after.asked === false && after.reason !== "already-asked") {
    assert.equal(after.persistent, true);
  }
  assert.equal(failing.calls, callsAfterBudget, "no unbounded retry loop");
});

test("attempts are per head, so a new head starts fresh", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  await askReplitOnce({ kv: store, mcp: failing, prNumber: 1, headSha: HEAD });
  const newHead = "d".repeat(40);
  const outcome = await askReplitOnce({ kv: store, mcp: mcp(), prNumber: 1, headSha: newHead });
  assert.equal(outcome.asked, true);
});
