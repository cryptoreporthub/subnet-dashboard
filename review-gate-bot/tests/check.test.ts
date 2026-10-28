import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { CHECK_NAME, gateConclusion, postGateCheck } from "../bot/lib/check.js";
import type { GateNext, GateState } from "../bot/lib/gate.js";

const HEAD = "a".repeat(40);
const MOVED = "b".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

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

test("only a mergeable gate is green, a FAIL is red, and everything still waiting needs action", () => {
  const expected: Record<GateNext, string> = {
    review: "action_required",
    await_cursor_ditto: "action_required",
    run_suite: "action_required",
    tag_replit: "action_required",
    await_replit: "action_required",
    needs_joshua: "action_required",
    mergeable: "success",
    blocked: "failure",
  };
  for (const [next, conclusion] of Object.entries(expected)) {
    assert.equal(gateConclusion(state(next as GateNext)), conclusion, next);
  }
});

test("a waiting head never reads as passed: not success, neutral or skipped, which branch rules count as passing", () => {
  const waiting: GateNext[] = ["review", "await_cursor_ditto", "run_suite", "tag_replit", "await_replit"];
  for (const next of waiting) {
    assert.ok(!["success", "neutral", "skipped"].includes(gateConclusion(state(next))), next);
  }
});

type Check = { name: string; sha: string; conclusion?: string; summary?: string };

/** The PR's head is read in the order given; the last value repeats. */
/** A delivery that reads the gate it was handed, then the same gate again under the lock. */
const same = (s: GateState) => ({ state: s, read: async () => s });

function world(heads: string[]) {
  const checks: Check[] = [];
  const store = new Map<string, unknown>();
  let reads = 0;
  const octokit = {
    rest: {
      pulls: {
        get: async () => ({ data: { head: { sha: heads[Math.min(reads++, heads.length - 1)] } } }),
      },
    },
  } as unknown as Octokit;
  const kv = {
    get: async (key: string) => store.get(key),
    put: async (key: string, value: unknown) => void store.set(key, value),
    delete: async (key: string) => void store.delete(key),
  } as unknown as HostKvApi;
  const createCheck = async (input: { name: string; sha: string }) => {
    const check: Check = { name: input.name, sha: input.sha };
    checks.push(check);
    return {
      update: async () => {},
      conclude: async (done: { conclusion: string; output?: { summary: string } }) => {
        check.conclusion = done.conclusion;
        check.summary = done.output?.summary;
      },
    };
  };
  return { checks, store, deps: { octokit, kv, ref: REF, createCheck } };
}

test("a mergeable gate at the live head posts a green review-gate check on that head", async () => {
  const w = world([HEAD]);
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("mergeable")) }), "posted");
  assert.deepEqual(w.checks.map((c) => [c.name, c.sha, c.conclusion]), [[CHECK_NAME, HEAD, "success"]]);
});

test("a head that moved before the post gets no check, green or otherwise", async () => {
  const w = world([MOVED]);
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("mergeable")) }), "stale-head");
  assert.deepEqual(w.checks, []);
});

test("a head that moves after the check opens is never concluded green", async () => {
  const w = world([HEAD, MOVED]);
  await postGateCheck({ ...w.deps, ...same(state("mergeable")) });
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
  assert.match(w.checks[0]?.summary ?? "", /head moved/i);
});

test("the summary names each reviewer's verdict and the next step, so a red or grey check explains itself", async () => {
  const w = world([HEAD]);
  await postGateCheck({ ...w.deps, ...same(state("await_cursor_ditto", { ditto: "missing", replit: "missing", suite: "missing" })) });
  const summary = w.checks[0]?.summary ?? "";
  for (const needle of ["MC", "Cursor", "Ditto", "Replit", "suite", "await_cursor_ditto"]) {
    assert.ok(summary.includes(needle), `${needle} missing from: ${summary}`);
  }
});

test("an unchanged gate state at the same head does not open another check; a changed one does", async () => {
  const w = world([HEAD]);
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("await_cursor_ditto", { ditto: "missing" })) }), "posted");
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("await_cursor_ditto", { ditto: "missing" })) }), "unchanged");
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("mergeable")) }), "posted");
  assert.deepEqual(w.checks.map((c) => c.conclusion), ["action_required", "success"]);
});

test("a delivery that read the gate earlier cannot conclude over a newer delivery's check", async () => {
  // The first delivery read the gate while it was still waiting, then stalls before it opens its check.
  // The gate turns green, and a second delivery concludes green. The first must not land after it.
  const w = world([HEAD]);
  let gate = state("await_cursor_ditto", { ditto: "missing" });
  const read = async () => gate;
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const stalled = async (input: { name: string; sha: string }) => {
    await held;
    return w.deps.createCheck(input);
  };
  const first = postGateCheck({ ...w.deps, createCheck: stalled, read, state: gate });
  await new Promise((resolve) => setImmediate(resolve));
  gate = state("mergeable");
  const second = postGateCheck({ ...w.deps, read, state: gate });
  // Give the newer delivery a chance to conclude first; a delivery that waits behind the stalled one
  // is still pending after this, and is released below.
  await Promise.race([second, new Promise((resolve) => setTimeout(resolve, 50))]);
  release();
  await Promise.all([first, second]);
  assert.equal(w.checks.at(-1)?.conclusion, "success", `the last check concluded: ${JSON.stringify(w.checks)}`);
});

test("the check reports the gate as read under the lock, not the state the delivery was handed", async () => {
  // Another process posted a newer verdict after this delivery read the gate. The fresh read is the truth.
  const w = world([HEAD]);
  const stale = state("await_cursor_ditto", { ditto: "missing" });
  const fresh = state("mergeable");
  await postGateCheck({ ...w.deps, state: stale, read: async () => fresh });
  assert.deepEqual(w.checks.map((c) => c.conclusion), ["success"]);
});

test("the same PR number and head in another repository is a different PR, so its check is posted", async () => {
  const w = world([HEAD]);
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("mergeable")) }), "posted");
  assert.equal(await postGateCheck({ ...w.deps, ref: { ...REF, owner: "someone-else" }, ...same(state("mergeable")) }), "posted");
  assert.equal(w.checks.length, 2);
});

test("a check that failed to open is retried by the next delivery", async () => {
  const w = world([HEAD]);
  const failing = { ...w.deps, createCheck: async () => { throw new Error("github 403"); } };
  await assert.rejects(postGateCheck({ ...failing, ...same(state("mergeable")) }), /403/);
  assert.equal(await postGateCheck({ ...w.deps, ...same(state("mergeable")) }), "posted");
});

test("a NEEDS-JOSHUA gate says so in the check, with the reason and the files or test IDs behind it", async () => {
  const w = world([HEAD]);
  await postGateCheck({ ...w.deps, ...same(state("needs_joshua", { suite: "needs-joshua", suiteDetail: "pytest.ini" })) });
  const summary = w.checks[0]?.summary ?? "";
  assert.match(summary, /NEEDS-JOSHUA/);
  assert.match(summary, /pytest\.ini/);
  assert.equal(w.checks[0]?.conclusion, "action_required");
});

