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
  assert.equal(await postGateCheck({ ...w.deps, state: state("mergeable") }), "posted");
  assert.deepEqual(w.checks.map((c) => [c.name, c.sha, c.conclusion]), [[CHECK_NAME, HEAD, "success"]]);
});

test("a head that moved before the post gets no check, green or otherwise", async () => {
  const w = world([MOVED]);
  assert.equal(await postGateCheck({ ...w.deps, state: state("mergeable") }), "stale-head");
  assert.deepEqual(w.checks, []);
});

test("a head that moves after the check opens is never concluded green", async () => {
  const w = world([HEAD, MOVED]);
  await postGateCheck({ ...w.deps, state: state("mergeable") });
  assert.equal(w.checks.length, 1);
  assert.equal(w.checks[0]?.conclusion, "cancelled");
  assert.match(w.checks[0]?.summary ?? "", /head moved/i);
});

test("the summary names each reviewer's verdict and the next step, so a red or grey check explains itself", async () => {
  const w = world([HEAD]);
  await postGateCheck({ ...w.deps, state: state("await_cursor_ditto", { ditto: "missing", replit: "missing", suite: "missing" }) });
  const summary = w.checks[0]?.summary ?? "";
  for (const needle of ["MC", "Cursor", "Ditto", "Replit", "suite", "await_cursor_ditto"]) {
    assert.ok(summary.includes(needle), `${needle} missing from: ${summary}`);
  }
});

test("an unchanged gate state at the same head does not open another check; a changed one does", async () => {
  const w = world([HEAD]);
  assert.equal(await postGateCheck({ ...w.deps, state: state("await_cursor_ditto", { ditto: "missing" }) }), "posted");
  assert.equal(await postGateCheck({ ...w.deps, state: state("await_cursor_ditto", { ditto: "missing" }) }), "unchanged");
  assert.equal(await postGateCheck({ ...w.deps, state: state("mergeable") }), "posted");
  assert.deepEqual(w.checks.map((c) => c.conclusion), ["action_required", "success"]);
});

test("a check that failed to open is retried by the next delivery", async () => {
  const w = world([HEAD]);
  const failing = { ...w.deps, createCheck: async () => { throw new Error("github 403"); } };
  await assert.rejects(postGateCheck({ ...failing, state: state("mergeable") }), /403/);
  assert.equal(await postGateCheck({ ...w.deps, state: state("mergeable") }), "posted");
});
