import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { CHECK_NAME, checkDedupeKey, postGateCheck, openGateCheckWorking } from "../bot/lib/check.js";
import { checkHoldFingerprint, type GateNext, type GateState } from "../bot/lib/gate.js";
import { suiteKey } from "../bot/lib/gh.js";
import { READER_EXPECTED_SCHEMA_VERSION } from "../bot/lib/pair-record.js";
import {
  newDeliveryBudget,
  resetDeliveryBudgetFactory,
  setDeliveryBudgetFactory,
  type ReadyPair,
} from "../bot/lib/pair-observation.js";

const HEAD = "a".repeat(40);
const MOVED = "b".repeat(40);
const BASE = "c".repeat(40);
const MERGE = "e".repeat(40);
const OTHER_MERGE = "d".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

function deliveryPair(): ReadyPair {
  return { kind: "ready", prNumber: REF.number, headSha: HEAD, baseTipSha: BASE, mergeBaseSha: MERGE, draft: false, baseRef: "main" };
}

function state(next: GateNext, overrides: Partial<GateState> = {}): GateState {
  return {
    headSha: HEAD,
    mc: "PASS",
    cursor: "PASS",
    ditto: "PASS",
    replit: "PASS",
    suite: "clean",
    replitTagged: true,
    next,
    ...overrides,
  };
}

const same = (s: GateState) => ({ state: s, read: async () => s });

type Check = { name: string; sha: string; conclusion?: string; summary?: string; status?: string };

type MergeBaseReply = string | null | "empty-sha";

type WorldOptions = {
  compareThrowOnCall?: number[];
};

function seedClean(w: ReturnType<typeof world>, gate: GateState = state("mergeable")) {
  w.store.set(suiteKey(REF, HEAD, BASE), {
    state: "clean",
    at: 1,
    schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
    mergeBaseSha: MERGE,
    checkHoldFingerprint: checkHoldFingerprint(gate),
  });
}

function world(
  heads: string[],
  bases: string[] = [MERGE],
  tips: string[] = [BASE],
  mergeBases: MergeBaseReply[] = [MERGE],
  options: WorldOptions = {},
) {
  const checks: Check[] = [];
  const store = new Map<string, unknown>();
  let reads = 0;
  let compareCalls = 0;
  const baseRepo = { owner: { login: REF.owner }, name: REF.repo };
  const octokit = {
    rest: {
      pulls: {
        get: async () => {
          const i = Math.min(reads, heads.length - 1);
          const baseSha = bases[Math.min(reads, bases.length - 1)];
          tips[Math.min(reads, tips.length - 1)];
          reads += 1;
          return {
            data: {
              number: REF.number,
              head: { sha: heads[i] },
              base: { sha: baseSha, ref: "main", repo: baseRepo },
              draft: false,
            },
          };
        },
        listFiles: async () => [],
        listReviews: async () => [],
      },
      issues: { listComments: async () => [] },
      repos: {
        getBranch: async () => ({
          data: { commit: { sha: tips[Math.min(Math.max(reads - 1, 0), tips.length - 1)] ?? BASE } },
        }),
        compareCommitsWithBasehead: async () => {
          const callIndex = compareCalls;
          compareCalls += 1;
          if (options.compareThrowOnCall?.includes(callIndex) === true) {
            throw new Error("compare 502");
          }
          const idx = Math.min(callIndex, mergeBases.length - 1);
          const mb = mergeBases[idx];
          return {
            data: {
              merge_base_commit:
                mb === null ? null : mb === "empty-sha" ? { sha: "" } : { sha: mb },
              files: [],
            },
          };
        },
      },
    },
  } as unknown as Octokit;
  const kv = {
    get: async (key: string) => store.get(key),
    put: async (key: string, value: unknown) => void store.set(key, value),
    delete: async (key: string) => void store.delete(key),
  } as unknown as HostKvApi;
  const baseCreateCheck = async (input: { name: string; sha: string }) => {
    const check: Check = { name: input.name, sha: input.sha };
    checks.push(check);
    return {
      update: async (patch: { status?: string; output?: { summary: string } }) => {
        if (patch.status !== undefined) {
          check.status = patch.status;
        }
      },
      conclude: async (done: { conclusion: string; output?: { summary: string } }) => {
        check.conclusion = done.conclusion;
        check.summary = done.output?.summary;
      },
    };
  };
  return {
    checks,
    store,
    pairReadCount: () => compareCalls,
    deps: { octokit, kv, ref: REF, createCheck: baseCreateCheck },
  };
}

type ConcludeTraceEntry = {
  kind: "non-cancel" | "cancel";
  conclusion: string;
  threw: boolean;
};

function instrumentCreateCheck(
  base: ReturnType<typeof world>["deps"]["createCheck"],
  trace: ConcludeTraceEntry[],
  policy: {
    nonCancelThrowsBeforeSuccess?: number;
    throwCancel?: boolean;
  },
) {
  let nonCancelAttempts = 0;
  const maxNonCancelThrow = policy.nonCancelThrowsBeforeSuccess ?? 0;
  return async (input: { name: string; sha: string }) => {
    const handle = await base(input);
    return {
      update: handle.update,
      conclude: async (done: { conclusion: string; output?: { summary: string } }) => {
        const isCancel = done.conclusion === "cancelled";
        const kind = isCancel ? "cancel" : "non-cancel";
        if (isCancel && policy.throwCancel === true) {
          trace.push({ kind, conclusion: done.conclusion, threw: true });
          throw new Error("github 502");
        }
        if (!isCancel && nonCancelAttempts < maxNonCancelThrow) {
          nonCancelAttempts += 1;
          trace.push({ kind, conclusion: done.conclusion, threw: true });
          throw new Error("github 502");
        }
        trace.push({ kind, conclusion: done.conclusion, threw: false });
        return handle.conclude(done);
      },
    };
  };
}

function createCheckFlakyConclude(
  base: ReturnType<typeof world>["deps"]["createCheck"],
  failBeforeSuccess: number,
) {
  let concludeAttempts = 0;
  return async (input: { name: string; sha: string }) => {
    const handle = await base(input);
    return {
      update: handle.update,
      conclude: async (done: { conclusion: string; output?: { summary: string } }) => {
        if (concludeAttempts < failBeforeSuccess) {
          concludeAttempts += 1;
          throw new Error("github 502");
        }
        return handle.conclude(done);
      },
    };
  };
}

test("A1 TC-reval-retry: first terminal conclude throws, revalidation same pair, retry posts", async () => {
  const w = world([HEAD]);
  seedClean(w, state("mergeable"));
  const createCheck = createCheckFlakyConclude(w.deps.createCheck, 1);
  const outcome = await postGateCheck({
    ...w.deps,
    createCheck,
    expectedPair: deliveryPair(),
    ...same(state("mergeable")),
  });
  assert.equal(outcome, "posted");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "success");
});

test("TC-reval-drift: failed conclude, revalidation observes drift, cancels working handle", async () => {
  const w = world([HEAD, HEAD, MOVED], [MERGE, MERGE, MERGE], [BASE, BASE, BASE], [MERGE, MERGE, MERGE]);
  seedClean(w, state("mergeable"));
  const workingCheck = await createCheckFlakyConclude(w.deps.createCheck, 1)({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(state("mergeable")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
  assert.match(w.checks[0]?.summary ?? "", /revalidation|drift|Superseded/i);
});

test("A2 TC-admit-drift: admission merge-base drift cancels supplied workingCheck, no second create", async () => {
  const w = world([HEAD], [MERGE], [BASE], [OTHER_MERGE]);
  seedClean(w, state("mergeable"));
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(state("mergeable")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
  assert.match(w.checks[0]?.summary ?? "", /admission|drift/i);
});

test("A2 TC-final-drift: final-fence drift uses existing workingCheck only", async () => {
  const w = world([HEAD, MOVED], [MERGE, MERGE], [BASE, BASE], [MERGE, MERGE]);
  seedClean(w, state("mergeable"));
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(state("mergeable")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
});

test("A3 TC-reval-readfail-ok: failed conclude then unreadable pair → pair-unverifiable on working handle", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 2,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD], [MERGE], [BASE], [MERGE], { compareThrowOnCall: [2] });
    seedClean(w, state("mergeable"));
    const workingCheck = await createCheckFlakyConclude(w.deps.createCheck, 1)({ name: CHECK_NAME, sha: HEAD });
    const outcome = await postGateCheck({
      ...w.deps,
      expectedPair: deliveryPair(),
      workingCheck,
      ...same(state("mergeable")),
    });
    assert.equal(outcome, "pair-unverifiable");
    assert.equal(w.checks.length, 1);
    assert.equal(w.checks[0]?.conclusion, "cancelled");
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("A3 Row A — failed terminal + unreadable pair + cancel throw: ordered trace, unresolved, no dedupe", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 2,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD], [MERGE], [BASE], [MERGE], { compareThrowOnCall: [2] });
    seedClean(w, state("mergeable"));
    const gate = state("mergeable");
    const dedupeKey = checkDedupeKey(REF, HEAD, BASE, MERGE, checkHoldFingerprint(gate));
    const trace: ConcludeTraceEntry[] = [];
    const createCheck = instrumentCreateCheck(w.deps.createCheck, trace, {
      nonCancelThrowsBeforeSuccess: 1,
      throwCancel: true,
    });
    const workingCheck = await createCheck({ name: CHECK_NAME, sha: HEAD });
    const outcome = await postGateCheck({
      ...w.deps,
      expectedPair: deliveryPair(),
      workingCheck,
      ...same(gate),
    });
    assert.equal(outcome, "finalization-unresolved");
    assert.equal(w.checks.length, 1);
    assert.equal(w.store.has(dedupeKey), false);
    assert.deepEqual(
      trace.map((e) => ({ kind: e.kind, threw: e.threw, conclusion: e.conclusion })),
      [
        { kind: "non-cancel", threw: true, conclusion: "success" },
        { kind: "cancel", threw: true, conclusion: "cancelled" },
      ],
    );
    assert.equal(w.pairReadCount(), 3);
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("A3 TC-reval-mutation-exhausted: zero githubMutations after failed terminal → finalization-unresolved", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 0,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD], [MERGE], [BASE], [MERGE], { compareThrowOnCall: [2] });
    seedClean(w, state("mergeable"));
    const workingCheck = await createCheckFlakyConclude(w.deps.createCheck, 1)({ name: CHECK_NAME, sha: HEAD });
    const outcome = await postGateCheck({
      ...w.deps,
      expectedPair: deliveryPair(),
      workingCheck,
      ...same(state("mergeable")),
    });
    assert.equal(outcome, "finalization-unresolved");
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("§9 Row B — double non-cancel terminal failure: two throws, one revalidation, no dedupe", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 2,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD]);
    seedClean(w, state("mergeable"));
    const gate = state("mergeable");
    const dedupeKey = checkDedupeKey(REF, HEAD, BASE, MERGE, checkHoldFingerprint(gate));
    const trace: ConcludeTraceEntry[] = [];
    const createCheck = instrumentCreateCheck(w.deps.createCheck, trace, { nonCancelThrowsBeforeSuccess: 99 });
    const outcome = await postGateCheck({
      ...w.deps,
      createCheck,
      expectedPair: deliveryPair(),
      ...same(gate),
    });
    assert.equal(outcome, "finalization-unresolved");
    assert.equal(w.checks.length, 1);
    assert.equal(w.store.has(dedupeKey), false);
    const nonCancel = trace.filter((e) => e.kind === "non-cancel");
    assert.equal(nonCancel.length, 2);
    assert.ok(nonCancel.every((e) => e.threw));
    assert.equal(trace.filter((e) => e.kind === "cancel").length, 0);
    assert.equal(w.pairReadCount(), 3);
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("TC-cancel-nodedupe: stale admission drift does not write check dedupe kv", async () => {
  const w = world([HEAD], [MERGE], [BASE], [OTHER_MERGE]);
  seedClean(w, state("mergeable"));
  const gate = state("mergeable");
  const hold = checkHoldFingerprint(gate);
  const dedupeKey = checkDedupeKey(REF, HEAD, BASE, MERGE, hold);
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(gate),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.store.has(dedupeKey), false);
});

test("RD-03: dedupe unchanged with open workingCheck does not leave extra concluded checks", async () => {
  const w = world([HEAD]);
  const gate = state("await_cursor_ditto", { ditto: "missing" });
  const first = await postGateCheck({ ...w.deps, expectedPair: deliveryPair(), ...same(gate) });
  assert.equal(first, "posted");
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const second = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(gate),
  });
  assert.equal(second, "unchanged");
  assert.equal(w.checks.filter((c) => c.conclusion === "action_required").length, 1);
});

test("Ditto TC-base-unavail-admit-mismatch-no-handle: stale-head, no merge-base blocker", async () => {
  const w = world([MOVED], [MERGE], [BASE], [null]);
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    ...same(state("await_cursor_ditto")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 0);
});

test("Ditto TC-base-unavail-admit-mismatch: mismatched base-unavailable cancels workingCheck", async () => {
  const w = world([MOVED], [MERGE], [BASE], [null]);
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    ...same(state("await_cursor_ditto")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
});

test("Ditto TC-base-unavail-admit-post: merge-base-absent posts on expectedPair head sha", async () => {
  const w = world([HEAD], [MERGE], [BASE], [null, null]);
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    ...same(state("await_cursor_ditto")),
  });
  assert.equal(outcome, "posted");
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.sha, HEAD);
  assert.equal(w.checks[0]?.conclusion, "action_required");
});

test("Ditto TC-base-unavail-reval-drift: revalidation drift stale-head, no blocker", async () => {
  const w = world([HEAD, MOVED], [MERGE, MERGE], [BASE, BASE], [null, null]);
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    ...same(state("await_cursor_ditto")),
  });
  assert.equal(outcome, "stale-head");
  assert.equal(w.checks.length, 0);
});

test("Ditto TC-base-unavail-admit2-post: second-admission base-unavailable branch fenced", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 3,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 2,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD, HEAD, HEAD], [MERGE, MERGE, MERGE], [BASE, BASE, BASE], [null, null, null], {
      compareThrowOnCall: [0],
    });
    const outcome = await postGateCheck({
      ...w.deps,
      expectedPair: deliveryPair(),
      ...same(state("await_cursor_ditto")),
    });
    assert.equal(outcome, "posted");
    assert.equal(w.checks.length, 1);
    assert.equal(w.checks[0]?.sha, HEAD);
    assert.equal(w.checks[0]?.conclusion, "action_required");
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("Ditto TC-reval-readfail-no-working: unreadable revalidation cancels created handle", async () => {
  setDeliveryBudgetFactory(() => ({
    admissionReads: 2,
    finalFenceReads: 2,
    revalidationReads: 1,
    githubMutations: 2,
    createCheckCount: 1,
  }));
  try {
    const w = world([HEAD], [MERGE], [BASE], [MERGE, MERGE], { compareThrowOnCall: [2] });
    seedClean(w, state("mergeable"));
    const createCheck = createCheckFlakyConclude(w.deps.createCheck, 1);
    const outcome = await postGateCheck({
      ...w.deps,
      createCheck,
      expectedPair: deliveryPair(),
      ...same(state("mergeable")),
    });
    assert.equal(outcome, "pair-unverifiable");
    assert.equal(w.checks.length, 1);
    assert.equal(w.checks[0]?.conclusion, "cancelled");
  } finally {
    resetDeliveryBudgetFactory();
  }
});

test("TC-open-update-fail: in_progress update throw still returns working handle for postGateCheck", async () => {
  const budget = newDeliveryBudget();
  const w = world([HEAD]);
  const createCheck = async (input: { name: string; sha: string }) => {
    const h = await w.deps.createCheck(input);
    return {
      update: async () => {
        throw new Error("github 403");
      },
      conclude: h.conclude,
    };
  };
  const handle = await openGateCheckWorking({
    octokit: w.deps.octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: MERGE,
    baseTipSha: BASE,
    createCheck,
    budget,
  });
  assert.notEqual(handle, undefined);
});
