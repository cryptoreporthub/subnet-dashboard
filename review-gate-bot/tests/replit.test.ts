import assert from "node:assert/strict";
import test from "node:test";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { createMemoryKv } from "@grok/agent-sdk/kv";
import {
  ASK_ATTEMPTS,
  askReplitOnce,
  __testOnly_askReplit,
  __testOnly_askReplitOnceCrossProcess,
  __testOnly_setInFlightLeaseMs,
  __testOnly_setRenewInFlightDuringCall,
  __testOnly_resetDiscoveryQueue,
  __testOnly_discoveryJoinCount,
  __testOnly_discoverySubscriberCount,
  __testOnly_discoveryIdle,
  __testOnly_ownerFailureWrite,
  IN_FLIGHT_LEASE_MS,
  REPLIT_TOOL,
  replitQuestion,
} from "../bot/lib/replit.js";
import { replitAskKey } from "../bot/lib/gate.js";
import { askDiscoveryBudgetMs, __testOnly_setLeaseMs } from "../bot/lib/lock.js";

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

test("ditto r4508316408: a failed success-record write does not permit a duplicate ask", async () => {
  const base = kv();
  const store: HostKvApi & { store: Map<string, unknown>; calls: number } = {
    store: base.store,
    calls: 0,
    get: base.get.bind(base),
    delete: base.delete.bind(base),
    async put(key, value) {
      const record = value as { askedAt?: number; deliveredAt?: number };
      if (record.askedAt !== undefined || record.deliveredAt !== undefined) {
        throw new Error("kv transient");
      }
      return base.put(key, value);
    },
  };
  const registry = mcp();
  const first = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(first.asked, true);
  assert.equal(registry.calls, 1);

  const second = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(second.asked, false);
  assert.equal(second.reason, "already-asked");
  assert.equal(registry.calls, 1, "must not ask Replit again");
  const record = store.store.get(replitAskKey(REF, HEAD)) as {
    inFlightAt?: number;
    askedAt?: number;
    deliveredAt?: number;
  };
  assert.ok(record.inFlightAt !== undefined);
  assert.equal(record.askedAt, undefined);
  assert.equal(record.deliveredAt, undefined, "both terminal writes failed; in-flight lease suppresses duplicate");
});

test("ditto r4511038426: a fresh in-flight claim suppresses a concurrent duplicate ask", async () => {
  const store = kv();
  const now = Date.now();
  await store.put(replitAskKey(REF, HEAD), { at: now, inFlightAt: now });
  const registry = mcp();
  const outcome = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(outcome.asked, false);
  assert.equal(outcome.reason, "already-asked");
  assert.equal(registry.calls, 0);
});

test("ditto r4511038925: a stale in-flight claim after crash permits retry", async () => {
  const store = kv();
  const stale = Date.now() - IN_FLIGHT_LEASE_MS - 1;
  await store.put(replitAskKey(REF, HEAD), { at: stale, inFlightAt: stale, claimNonce: "stale" });
  const registry = mcp();
  const outcome = await askReplitOnce({ kv: store, mcp: registry, ref: REF, headSha: HEAD });
  assert.equal(outcome.asked, true);
  assert.equal(registry.calls, 1);
});

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Plain get/put/delete only — matches hosted KV without CAS. */
function plainKvOnly(): HostKvApi & { store: Map<string, unknown> } {
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

/** CAS-capable KV without atomic create — production CAS hosts expose `putIfAbsent`. */
type CasMemoryKv = ReturnType<typeof createMemoryKv>;

function casKvWithoutPutIfAbsent(): CasMemoryKv {
  const memory = createMemoryKv();
  Reflect.deleteProperty(memory, "putIfAbsent");
  assert.equal(typeof memory.putIfAbsent, "undefined");
  return memory;
}

test("ditto r4511210612: a rejecting KV renewal does not cause unhandled rejection", async () => {
  const base = kv();
  let rejectRenewal = false;
  const store: HostKvApi & { store: Map<string, unknown> } = {
    store: base.store,
    get: base.get.bind(base),
    delete: base.delete.bind(base),
    async put(key, value) {
      const record = value as { inFlightAt?: number; askedAt?: number };
      if (rejectRenewal && record.inFlightAt !== undefined && record.askedAt === undefined) {
        const existing = base.store.get(key) as { claimNonce?: string } | undefined;
        if (existing?.claimNonce !== undefined && record.inFlightAt !== (existing as { inFlightAt?: number }).inFlightAt) {
          throw new Error("kv renew transient");
        }
      }
      return base.put(key, value);
    },
  };
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  const slow = {
    names: () => ["replit"],
    listTools: async () => [{ name: REPLIT_TOOL }],
    callTool: async () => {
      rejectRenewal = true;
      await pending;
      return { isError: false, content: [{ type: "text", text: "ok" }] };
    },
  } as unknown as HostMcpRegistry;
  const ask = __testOnly_askReplit({ kv: store, mcp: slow, ref: REF, headSha: HEAD });
  await sleep(60);
  release();
  const outcome = await ask;
  assert.equal(outcome.asked, true);
});

test("ditto r4515088492: timed-out discovery does not stack another listTools", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  try {
    const store = plainKvOnly();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    let listToolsCalls = 0;
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const headA = "e".repeat(40);
    const headB = "f".repeat(40);
    const first = __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp: slow,
      ref: REF,
      headSha: headA,
    });
    await sleep(1_100);
    const firstDone = await Promise.race([
      first,
      sleep(2_000).then(() => {
        throw new Error("first ask wedged");
      }),
    ]);
    assert.equal(firstDone.asked, false);
    assert.equal(listToolsCalls, 1);
    const second = __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp: slow,
      ref: REF,
      headSha: headB,
    });
    await sleep(50);
    assert.equal(listToolsCalls, 1, "second head must not start discovery while the first listTools is still live");
    releaseListTools();
    await first;
    await second;
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("ditto r4515179842: queued discovery abandoned after timeout does not run listTools", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  try {
    const store = plainKvOnly();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    let listToolsCalls = 0;
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const headA = "a".repeat(40);
    const headB = "b".repeat(40);
    const first = __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha: headA });
    await sleep(50);
    assert.equal(listToolsCalls, 1);
    const second = __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha: headB });
    const secondDone = await Promise.race([
      second,
      sleep(3_000).then(() => {
        throw new Error("second ask wedged");
      }),
    ]);
    assert.equal(secondDone.asked, false);
    if (!secondDone.asked) {
      assert.equal(secondDone.reason, "unavailable");
    }
    assert.equal(listToolsCalls, 1, "queued second must not call listTools before first settles");
    releaseListTools();
    await first;
    await second;
    await sleep(50);
    assert.equal(listToolsCalls, 1, "abandoned queued discovery must not run listTools after first settles");
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("ditto r4513514628 / r4513568040: discovery timeout returns without wedging; later caller recovers", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  try {
    const store = plainKvOnly();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    let fastListTools = 0;
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const fast = {
      names: () => ["replit"],
      listTools: async () => {
        fastListTools += 1;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const head = "d".repeat(40);
    const first = __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha: head });
    const firstDone = await Promise.race([
      first,
      sleep(3_000).then(() => {
        throw new Error("first ask wedged on a stuck listTools");
      }),
    ]);
    assert.equal(firstDone.asked, false);
    if (!firstDone.asked) {
      assert.equal(firstDone.reason, "unavailable");
    }
    releaseListTools();
    await first;
    const second = await __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: fast, ref: REF, headSha: head });
    assert.equal(fastListTools, 1, "later caller may discover after the serialized slot drains");
    assert.equal(second.asked, true);
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("pr-1522 8h: CAS KV returns unavailable when listTools hangs; later head discovers after release", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  const budget = askDiscoveryBudgetMs();
  try {
    const store = createMemoryKv();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    let listToolsCalls = 0;
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const headA = "8".repeat(40);
    const headB = "9".repeat(40);
    const started = Date.now();
    const first = __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp: slow,
      ref: REF,
      headSha: headA,
    });
    const firstDone = await Promise.race([
      first,
      sleep(budget + 2_000).then(() => {
        throw new Error("CAS ask wedged without discovery budget");
      }),
    ]);
    assert.equal(firstDone.asked, false);
    if (!firstDone.asked) {
      assert.equal(firstDone.reason, "unavailable");
    }
    assert.ok(Date.now() - started < budget + 1_500, "must finish within discovery budget, not hang forever");
    assert.equal(listToolsCalls, 1);
    releaseListTools();
    await first;
    await __testOnly_discoveryIdle(slow);
    const second = await __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp: slow,
      ref: REF,
      headSha: headB,
    });
    assert.equal(second.asked, true);
    assert.equal(listToolsCalls, 2, "coalesced discovery must not stack parallel listTools flights");
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("pr-1522 8h: plain KV times out many heads with one listTools; fresh caller succeeds after release", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  const budget = askDiscoveryBudgetMs();
  try {
    const store = plainKvOnly();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    let listToolsCalls = 0;
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const heads = ["0", "1", "2", "3", "4"].map((d) => d.repeat(40));
    const asks = heads.map((headSha) =>
      __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha }),
    );
    const outcomes = await Promise.all(
      asks.map((ask) =>
        Promise.race([
          ask,
          sleep(budget + 2_000).then(() => {
            throw new Error("queued ask wedged without discovery budget");
          }),
        ]),
      ),
    );
    for (const outcome of outcomes) {
      assert.equal(outcome.asked, false);
      if (!outcome.asked) {
        assert.equal(outcome.reason, "unavailable");
      }
    }
    assert.equal(listToolsCalls, 1);
    assert.equal(__testOnly_discoveryJoinCount(), 0, "all barrier callers must detach after timing out");
    assert.equal(__testOnly_discoverySubscriberCount(), 0, "timed-out callers must unregister from discovery fan-out");
    releaseListTools();
    await Promise.all(asks);
    await __testOnly_discoveryIdle(slow);
    const freshHead = "f".repeat(40);
    const fresh = await __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha: freshHead });
    assert.equal(fresh.asked, true);
    assert.equal(listToolsCalls, 2, "after release, exactly one follow-up discovery flight");
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("pr-1522 8h REVISE: repeated hung-listTools batches detach subscribers", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  const budget = askDiscoveryBudgetMs();
  try {
    const store = plainKvOnly();
    const batches = 3;
    const headsPerBatch = 4;
    let listToolsCalls = 0;
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    const slow = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const pendingAsks: Promise<unknown>[] = [];
    for (let batch = 0; batch < batches; batch += 1) {
      const heads = Array.from({ length: headsPerBatch }, (_, i) =>
        String(batch * headsPerBatch + i).repeat(40),
      );
      const asks = heads.map((headSha) =>
        __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha }),
      );
      pendingAsks.push(...asks);
      const outcomes = await Promise.all(
        asks.map((ask) =>
          Promise.race([
            ask,
            sleep(budget + 2_000).then(() => {
              throw new Error("batch ask wedged without discovery budget");
            }),
          ]),
        ),
      );
      for (const outcome of outcomes) {
        assert.equal(outcome.asked, false);
        if (!outcome.asked) {
          assert.equal(outcome.reason, "unavailable");
        }
      }
      assert.equal(listToolsCalls, 1, "one hung listTools shared across hung batches");
      assert.equal(__testOnly_discoveryJoinCount(), 0);
      assert.equal(__testOnly_discoverySubscriberCount(), 0);
    }
    releaseListTools();
    await Promise.all(pendingAsks);
    await __testOnly_discoveryIdle(slow);
    const fresh = await __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp: slow,
      ref: REF,
      headSha: "a".repeat(40),
    });
    assert.equal(fresh.asked, true);
    assert.equal(listToolsCalls, 2, "single recovery listTools after one release");
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("pr-1522 8h v3: registry-scoped discovery does not inherit another registry result", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  const budget = askDiscoveryBudgetMs();
  try {
    const storeA = plainKvOnly();
    const storeB = plainKvOnly();
    let releaseHung: () => void = () => {};
    const hungGate = new Promise<void>((resolve) => {
      releaseHung = resolve;
    });
    let callsAvailable = 0;
    let callsUnavailable = 0;
    const availableMcp = {
      names: () => ["replit"],
      listTools: async () => {
        callsAvailable += 1;
        await hungGate;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const unavailableMcp = {
      names: () => ["replit"],
      listTools: async () => {
        callsUnavailable += 1;
        return [];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const headAvailable = "b".repeat(40);
    const headUnavailable = "c".repeat(40);
    const hungAsk = __testOnly_askReplitOnceCrossProcess({
      kv: storeA,
      mcp: availableMcp,
      ref: REF,
      headSha: headAvailable,
    });
    const quickAsk = __testOnly_askReplitOnceCrossProcess({
      kv: storeB,
      mcp: unavailableMcp,
      ref: REF,
      headSha: headUnavailable,
    });
    const [hungOutcome, quickOutcome] = await Promise.all([
      Promise.race([
        hungAsk,
        sleep(budget + 2_000).then(() => {
          throw new Error("available-registry ask wedged");
        }),
      ]),
      Promise.race([
        quickAsk,
        sleep(budget + 2_000).then(() => {
          throw new Error("unavailable-registry ask wedged");
        }),
      ]),
    ]);
    assert.equal(hungOutcome.asked, false);
    if (!hungOutcome.asked) {
      assert.equal(hungOutcome.reason, "unavailable");
    }
    assert.equal(quickOutcome.asked, false);
    if (!quickOutcome.asked) {
      assert.equal(quickOutcome.reason, "unavailable");
    }
    assert.equal(callsAvailable, 1, "hung registry must own its sole listTools");
    assert.equal(callsUnavailable, 1, "fast registry must run its own listTools");
    assert.equal(__testOnly_discoveryJoinCount(), 0);
    releaseHung();
    await hungAsk;
    await __testOnly_discoveryIdle(availableMcp);
    const recover = await __testOnly_askReplitOnceCrossProcess({
      kv: storeA,
      mcp: availableMcp,
      ref: REF,
      headSha: "d".repeat(40),
    });
    assert.equal(recover.asked, true);
    assert.equal(callsAvailable, 2);
    assert.equal(callsUnavailable, 1, "unavailable registry must not pick up available boolean");
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("pr-1522 8h v4: resetDiscoveryQueue prevents stale flight finally on reused mcp", async () => {
  __testOnly_resetDiscoveryQueue();
  __testOnly_setLeaseMs(1_400);
  const budget = askDiscoveryBudgetMs();
  try {
    const store = plainKvOnly();
    let releaseHang: () => void = () => {};
    const hangGate = new Promise<void>((resolve) => {
      releaseHang = resolve;
    });
    let listToolsCalls = 0;
    const mcp = {
      names: () => ["replit"],
      listTools: async () => {
        listToolsCalls += 1;
        if (listToolsCalls === 1) {
          await hangGate;
        }
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const hungAsk = __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp,
      ref: REF,
      headSha: "1".repeat(40),
    });
    const firstOutcome = await Promise.race([
      hungAsk,
      sleep(budget + 2_000).then(() => {
        throw new Error("pre-reset ask wedged");
      }),
    ]);
    assert.equal(firstOutcome.asked, false);
    assert.equal(listToolsCalls, 1);
    __testOnly_resetDiscoveryQueue();
    const afterReset = __testOnly_askReplitOnceCrossProcess({
      kv: store,
      mcp,
      ref: REF,
      headSha: "2".repeat(40),
    });
    releaseHang();
    const recovered = await Promise.race([
      afterReset,
      sleep(budget + 2_000).then(() => {
        throw new Error("post-reset ask wedged — stale flight finally may have cleared in-flight");
      }),
    ]);
    assert.equal(recovered.asked, true);
    assert.equal(listToolsCalls, 2);
    await hungAsk.catch(() => undefined);
  } finally {
    __testOnly_setLeaseMs(undefined);
    __testOnly_resetDiscoveryQueue();
  }
});

test("ditto r4513373769: ask lease renews during slow listTools so a second process cannot take over", async () => {
  __testOnly_setLeaseMs(300);
  try {
    const store = createMemoryKv();
    let releaseListTools: () => void = () => {};
    const listToolsBlocked = new Promise<void>((resolve) => {
      releaseListTools = resolve;
    });
    const slowDiscovery = {
      names: () => ["replit"],
      listTools: async () => {
        await listToolsBlocked;
        return [{ name: REPLIT_TOOL }];
      },
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry;
    const fast = mcp();
    const slowAsk = __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slowDiscovery, ref: REF, headSha: HEAD });
    await sleep(400);
    const blocked = await __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: fast, ref: REF, headSha: HEAD });
    releaseListTools();
    await slowAsk;
    assert.equal(blocked.asked, false);
    assert.equal(blocked.reason, "already-asked");
    assert.equal(fast.calls, 0, "must not reach MCP while discovery holds the ask lease");
  } finally {
    __testOnly_setLeaseMs(undefined);
  }
});

test("ditto r4508317090: cross-process lease blocks a second handler before MCP", async () => {
  __testOnly_setInFlightLeaseMs(120);
  __testOnly_setRenewInFlightDuringCall(true);
  try {
    const store = createMemoryKv();
    let releaseSlow: () => void = () => {};
    const slowDone = new Promise<void>((resolve) => {
      releaseSlow = resolve;
    });
    const slow = {
      names: () => ["replit"],
      listTools: async () => [{ name: REPLIT_TOOL }],
      callTool: async () => {
        await Promise.race([slowDone, sleep(400)]);
        return { isError: false, content: [{ type: "text", text: "ok" }] };
      },
    } as unknown as HostMcpRegistry;
    const fast = mcp();
    const slowAsk = __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: slow, ref: REF, headSha: HEAD });
    await sleep(50);
    const blocked = await __testOnly_askReplitOnceCrossProcess({ kv: store, mcp: fast, ref: REF, headSha: HEAD });
    releaseSlow();
    await slowAsk;
    assert.equal(blocked.asked, false);
    assert.equal(blocked.reason, "already-asked");
    assert.equal(fast.calls, 0, "must not call Replit while another handler holds the ask lease");
  } finally {
    __testOnly_setInFlightLeaseMs(undefined);
    __testOnly_setRenewInFlightDuringCall(true);
  }
});

test("ditto r4511110608: in-flight renewal blocks a second process during a slow call", async () => {
  __testOnly_setInFlightLeaseMs(120);
  __testOnly_setRenewInFlightDuringCall(true);
  try {
    const store = kv();
    let releaseSlow: () => void = () => {};
    const slowDone = new Promise<void>((resolve) => {
      releaseSlow = resolve;
    });
    const slow = {
      names: () => ["replit"],
      listTools: async () => [{ name: REPLIT_TOOL }],
      callTool: async () => {
        await Promise.race([slowDone, sleep(400)]);
        return { isError: false, content: [{ type: "text", text: "ok" }] };
      },
    } as unknown as HostMcpRegistry;
    const fast = mcp();
    const slowAsk = __testOnly_askReplit({ kv: store, mcp: slow, ref: REF, headSha: HEAD });
    await sleep(50);
    const blocked = await __testOnly_askReplit({ kv: store, mcp: fast, ref: REF, headSha: HEAD });
    releaseSlow();
    await slowAsk;
    assert.equal(blocked.asked, false);
    assert.equal(blocked.reason, "already-asked");
    assert.equal(fast.calls, 0, "must not call Replit while the first ask is in flight");
  } finally {
    __testOnly_setInFlightLeaseMs(undefined);
    __testOnly_setRenewInFlightDuringCall(true);
  }
});

test("ditto r4511438066: absent-key failure write fails closed without putIfAbsent", async () => {
  const head = "f".repeat(40);
  const memory = casKvWithoutPutIfAbsent();
  const key = replitAskKey(REF, head);
  let interpose = false;
  const origGetWithVersion = memory.getWithVersion.bind(memory);
  memory.getWithVersion = async (k) => {
    const entry = await origGetWithVersion(k);
    if (interpose && k === key) {
      interpose = false;
      const now = Date.now();
      await memory.put(key, { at: now, askedAt: now, claimNonce: "winner" });
    }
    return entry;
  };

  interpose = true;
  const outcome = await askReplitOnce({
    kv: memory,
    mcp: mcp({ available: false }),
    ref: REF,
    headSha: head,
  });
  assert.equal(outcome.asked, false);
  const record = (await memory.get(key)) as { askedAt?: number; failedAttempts?: number };
  assert.ok(record.askedAt !== undefined);
  assert.equal(record.failedAttempts, undefined);
});

test("ditto r4511438066: absent-key claim write fails closed without putIfAbsent", async () => {
  const head = "f1".repeat(20);
  const memory = casKvWithoutPutIfAbsent();
  const key = replitAskKey(REF, head);
  let interpose = false;
  const origGetWithVersion = memory.getWithVersion.bind(memory);
  memory.getWithVersion = async (k) => {
    const entry = await origGetWithVersion(k);
    if (interpose && k === key) {
      interpose = false;
      const now = Date.now();
      await memory.put(key, { at: now, askedAt: now, claimNonce: "winner" });
    }
    return entry;
  };

  interpose = true;
  const outcome = await __testOnly_askReplit({
    kv: memory,
    mcp: mcp(),
    ref: REF,
    headSha: head,
  });
  assert.equal(outcome.asked, false);
  const record = (await memory.get(key)) as { askedAt?: number; inFlightAt?: number };
  assert.ok(record.askedAt !== undefined);
  assert.equal(record.inFlightAt, undefined, "must not replace terminal success with a claim");
});

test("ditto r4511211560: failure bookkeeping cannot overwrite concurrent success", async () => {
  const head = "e".repeat(40);
  const memory = createMemoryKv();
  const key = replitAskKey(REF, head);
  let interpose = false;
  const origGetWithVersion = memory.getWithVersion.bind(memory);
  memory.getWithVersion = async (k) => {
    const entry = await origGetWithVersion(k);
    if (interpose && k === key) {
      interpose = false;
      const now = Date.now();
      await memory.put(key, { at: now, askedAt: now, claimNonce: "winner" });
    }
    return entry;
  };

  interpose = true;
  const outcome = await askReplitOnce({
    kv: memory as HostKvApi,
    mcp: mcp({ available: false }),
    ref: REF,
    headSha: head,
  });
  assert.equal(outcome.asked, false);
  const record = (await memory.get(key)) as { askedAt?: number; failedAttempts?: number };
  assert.ok(record.askedAt !== undefined);
  assert.equal(record.failedAttempts, undefined);
  const again = await askReplitOnce({ kv: memory as HostKvApi, mcp: mcp(), ref: REF, headSha: head });
  assert.equal(again.asked, false);
  assert.equal(again.reason, "already-asked");
});

test("ditto r4511316326: owner failure write cannot erase recorded success", async () => {
  const store = kv();
  const key = replitAskKey(REF, HEAD);
  const nonce = "same-owner";
  const now = Date.now();
  await store.put(key, { at: now, askedAt: now, claimNonce: nonce });
  const wrote = await __testOnly_ownerFailureWrite(store, REF, HEAD, nonce, 1);
  assert.equal(wrote, false);
  const record = store.store.get(key) as { askedAt?: number; failedAttempts?: number };
  assert.ok(record.askedAt !== undefined);
  assert.equal(record.failedAttempts, undefined);
});

test("ditto r4511267518: a stale failure cannot roll back a newer attempt count", async () => {
  __testOnly_setInFlightLeaseMs(80);
  __testOnly_setRenewInFlightDuringCall(false);
  try {
    const store = kv();
    let releaseA: () => void = () => {};
    const pendingA = new Promise<void>((resolve) => {
      releaseA = resolve;
    });
    const slowA = {
      names: () => ["replit"],
      listTools: async () => [{ name: REPLIT_TOOL }],
      callTool: async () => {
        await pendingA;
        throw new Error("stale fail");
      },
    } as unknown as HostMcpRegistry;
    const failing = mcp({ throwOnCall: true });
    const askA = __testOnly_askReplit({ kv: store, mcp: slowA, ref: REF, headSha: HEAD });
    await sleep(90);

    const askB = await __testOnly_askReplit({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
    assert.equal(askB.asked, false);
    if (!askB.asked && askB.reason !== "already-asked") {
      assert.equal(askB.attempts, 1);
    }

    const askC = await __testOnly_askReplit({ kv: store, mcp: failing, ref: REF, headSha: HEAD });
    assert.equal(askC.asked, false);
    if (!askC.asked && askC.reason !== "already-asked") {
      assert.equal(askC.attempts, 2);
    }

    const nonceBeforeLate = (store.store.get(replitAskKey(REF, HEAD)) as { claimNonce?: string }).claimNonce;
    releaseA();
    const lateA = await askA;
    assert.equal(lateA.asked, false);

    const record = store.store.get(replitAskKey(REF, HEAD)) as {
      failedAttempts?: number;
      claimNonce?: string;
    };
    assert.equal(record.failedAttempts, 2);
    assert.equal(record.claimNonce, nonceBeforeLate);
    assert.equal(failing.calls, 2, "stale A must not consume another attempt slot");
  } finally {
    __testOnly_setInFlightLeaseMs(undefined);
    __testOnly_setRenewInFlightDuringCall(true);
  }
});

test("ditto r4511110136: a stale attempt cannot erase a newer successful ask", async () => {
  __testOnly_setInFlightLeaseMs(80);
  __testOnly_setRenewInFlightDuringCall(false);
  try {
    const store = kv();
    let releaseSlowFail: () => void = () => {};
    const slowFailure = new Promise<void>((_, reject) => {
      releaseSlowFail = () => reject(new Error("late fail"));
    });
    const slowFail = {
      names: () => ["replit"],
      listTools: async () => [{ name: REPLIT_TOOL }],
      callTool: async () => {
        await slowFailure;
        throw new Error("late fail");
      },
    } as unknown as HostMcpRegistry;
    const fast = mcp();
    const late = __testOnly_askReplit({ kv: store, mcp: slowFail, ref: REF, headSha: HEAD });
    await sleep(90);
    const reclaim = await __testOnly_askReplit({ kv: store, mcp: fast, ref: REF, headSha: HEAD });
    releaseSlowFail();
    await late;
    const record = store.store.get(replitAskKey(REF, HEAD)) as { askedAt?: number; deliveredAt?: number };
    assert.equal(reclaim.asked, true);
    assert.ok(record.askedAt !== undefined || record.deliveredAt !== undefined);
    const again = await __testOnly_askReplit({ kv: store, mcp: fast, ref: REF, headSha: HEAD });
    assert.equal(again.asked, false);
    if (!again.asked) {
      assert.equal(again.reason, "already-asked");
    }
    assert.equal(fast.calls, 1);
  } finally {
    __testOnly_setInFlightLeaseMs(undefined);
    __testOnly_setRenewInFlightDuringCall(true);
  }
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
