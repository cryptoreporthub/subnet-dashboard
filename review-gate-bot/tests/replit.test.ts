import assert from "node:assert/strict";
import test from "node:test";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { ASK_ATTEMPTS, askReplitOnce, REPLIT_TOOL, replitQuestion } from "../bot/lib/replit.js";
import { replitAskKey } from "../bot/lib/gate.js";

const HEAD = "c".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1 };

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
  const first = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(first.asked, true);
  assert.ok(store.store.has(replitAskKey(REF, HEAD)));

  const second = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(second.asked, false);
  assert.equal(second.reason, "already-asked");
  assert.equal(registry.calls, 1, "one ask, not two");
});

test("a successful ask is never a review and never touches the gate", async () => {
  // There is no `reviewed` outcome at all: the type system is the assertion.
  const outcome = await askReplitOnce({ kv: kv(), mcp: mcp(), ref: REF, headSha: HEAD });
  assert.equal(outcome.asked, true);
  const keys = Object.keys(outcome);
  assert.equal(keys.includes("reviewed"), false, "an ask cannot be counted as a review");
  assert.equal(keys.includes("verdict"), false);
});

test("the question names the PR and the head, and keeps Replit on the free effort level", () => {
  const head = "65b33e0e3c601f7a4a436b0781d76e33fa37030c";
  const question = replitQuestion(1522, head);
  assert.match(question, /PR #1522/);
  assert.ok(question.includes(head), "the full head SHA is named");
  assert.match(question, /free\/default effort level/);
  assert.match(question, /do not ask which effort level/);
  assert.match(question, /do not offer power mode/);
  assert.match(question, /Post your verdict on the PR/);
});

test("a failed ask is retried on the next call instead of being dropped", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  const first = await askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
  assert.equal(first.asked, false);
  assert.equal(first.reason, "error");
  if (!first.persistent) {
    assert.equal(first.attempts, 1);
  }

  // The old behaviour: nothing recorded, nothing retried, silence. Now the
  // attempt is recorded and a later call tries again.
  const retry = await askReplitOnce({ kv: store, mcp: mcp(), ref: REF, headSha: HEAD });
  assert.equal(retry.asked, true, "the retry must actually reach the connector");
});

test("an unavailable connector is reported as a failure, not as success", async () => {
  const outcome = await askReplitOnce({
    kv: kv(),
    mcp: mcp({ available: false }),
    ref: REF,
    headSha: HEAD,
  });
  assert.equal(outcome.asked, false);
  assert.equal(outcome.reason, "unavailable");
});

test("an MCP error result is a failure", async () => {
  const outcome = await askReplitOnce({
    kv: kv(),
    mcp: mcp({ isError: true }),
    ref: REF,
    headSha: HEAD,
  });
  assert.equal(outcome.asked, false);
  assert.equal(outcome.reason, "error");
});

test("persistent failure surfaces after the attempt budget, and then stops trying", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  let last = await askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
  for (let i = 1; i < ASK_ATTEMPTS; i += 1) {
    last = await askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
  }
  assert.equal(last.asked, false);
  if (last.asked === false && last.reason !== "already-asked") {
    assert.equal(last.persistent, true, "the failure must be marked persistent so the channel logs it");
    assert.equal(last.attempts, ASK_ATTEMPTS);
  }

  const callsAfterBudget = failing.calls;
  const after = await askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
  assert.equal(after.asked, false);
  if (after.asked === false && after.reason !== "already-asked") {
    assert.equal(after.persistent, true);
  }
  assert.equal(failing.calls, callsAfterBudget, "no unbounded retry loop");
});

test("attempts are per head, so a new head starts fresh", async () => {
  const store = kv();
  const failing = mcp({ throwOnCall: true });
  await askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
  const newHead = "d".repeat(40);
  const outcome = await askReplitOnce({ kv: store, mcp: mcp(), ref: REF, headSha: newHead });
  assert.equal(outcome.asked, true);
});

const settle = () => new Promise<void>((resolve) => setImmediate(resolve));

/** An MCP whose call takes a moment, so overlapping callers really overlap. */
function slowMcp(outcome: "ok" | "error"): HostMcpRegistry & { calls: number } {
  const state = { calls: 0 };
  const registry = {
    get calls() {
      return state.calls;
    },
    names: () => ["replit"],
    listTools: async () => [{ name: REPLIT_TOOL }],
    callTool: async () => {
      state.calls += 1;
      await settle();
      return outcome === "ok"
        ? { isError: false, content: [{ type: "text", text: "ok" }] }
        : { isError: true, content: [{ type: "text", text: "busy" }] };
    },
  };
  return registry as unknown as HostMcpRegistry & { calls: number };
}

test("overlapping calls for one head ask Replit once", async () => {
  const store = kv();
  const registry = slowMcp("ok");
  const outcomes = await Promise.all(
    Array.from({ length: 6 }, () => askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD })),
  );
  assert.equal(registry.calls, 1, "one ask, however many events arrived together");
  assert.equal(outcomes.filter((o) => o.asked).length, 1);
});

test("overlapping failing calls spend the attempt budget once, not once per caller", async () => {
  const store = kv();
  const registry = slowMcp("error");
  await Promise.all(
    Array.from({ length: 6 }, () => askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD })),
  );
  assert.equal(registry.calls, ASK_ATTEMPTS);
});

test("a late failure can never overwrite a recorded success", async () => {
  const store = kv();
  const ok = slowMcp("ok");
  await askReplitOnce({ kv: store, mcp: ok, ref: REF, headSha: HEAD });
  const failing = slowMcp("error");
  await Promise.all([
    askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD }),
    askReplitOnce({ kv: store, mcp: failing, ref: REF, headSha: HEAD }),
  ]);
  assert.equal(failing.calls, 0);
  assert.ok((store.store.get(replitAskKey(REF, HEAD)) as { askedAt?: number }).askedAt !== undefined);
});

test("an MCP error that echoes a credential is scrubbed before it is stored or returned", async () => {
  const token = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0";
  const store = kv();
  const registry = {
    names: () => ["replit"],
    listTools: async () => [{ name: REPLIT_TOOL }],
    callTool: async () => ({ isError: true, content: [{ type: "text", text: `auth failed for ${token}` }] }),
  } as unknown as HostMcpRegistry;
  const outcome = await askReplitOnce({ kv: store, mcp: registry, ref: { owner: "o", repo: "r", number: 1 }, headSha: "a".repeat(40) });
  assert.equal(JSON.stringify(outcome).includes(token), false, "the outcome carries no credential");
  assert.equal(JSON.stringify([...store.store.entries()]).includes(token), false, "the stored failure carries no credential");
});
