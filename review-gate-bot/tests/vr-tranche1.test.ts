/**
 * Fix-4 acceptance matrix B tranche 1 (VR-pgc / VR-csr / VR-tool × V1–V3).
 * Plan: plan-1522-fix4-replit6691536655-contracts-integrated.md §8 + §11.
 */
import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { CHECK_NAME, checkDedupeKey, postGateCheck } from "../bot/lib/check.js";
import { checkHoldFingerprint, type GateNext, type GateState } from "../bot/lib/gate.js";
import { suiteKey } from "../bot/lib/gh.js";
import { READER_EXPECTED_SCHEMA_VERSION, RECORD_VERSION_MISMATCH_DETAIL } from "../bot/lib/pair-record.js";
import type { ReadyPair } from "../bot/lib/pair-observation.js";
import { marker } from "../bot/lib/verdicts.js";
import checkGateState from "../bot/tools/check_gate_state.js";
import compareSuiteRuns from "../bot/tools/compare_suite_runs.js";

const HEAD = "a".repeat(40);
const OLD = "b".repeat(40);
const BASE = "c".repeat(40);
const MERGE = "e".repeat(40);
const WRONG_MB = "f".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const KEY = "cont:github-pr:cryptoreporthub/subnet-dashboard#1522";
const ME = "simi-revision[bot]";

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

type Check = { name: string; sha: string; conclusion?: string; summary?: string };

function world() {
  const checks: Check[] = [];
  const store = new Map<string, unknown>();
  const baseRepo = { owner: { login: REF.owner }, name: REF.repo };
  const octokit = {
    rest: {
      pulls: {
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: HEAD },
            base: { sha: MERGE, ref: "main", repo: baseRepo },
            draft: false,
          },
        }),
        listFiles: async () => [],
        listReviews: async () => [],
      },
      issues: { listComments: async () => [] },
      repos: {
        getBranch: async () => ({ data: { commit: { sha: BASE } } }),
        compareCommitsWithBasehead: async () => ({
          data: { merge_base_commit: { sha: MERGE }, files: [] },
        }),
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

function seedInvalidSuite(
  store: Map<string, unknown>,
  gate: GateState,
  variant: "v1-omit-mb" | "v2-wrong-mb" | "v3-stale-schema",
) {
  const hold = checkHoldFingerprint(gate);
  const base: Record<string, unknown> = {
    state: "clean",
    at: 1,
    checkHoldFingerprint: hold,
  };
  if (variant === "v1-omit-mb") {
    base.schemaVersion = READER_EXPECTED_SCHEMA_VERSION;
  } else if (variant === "v2-wrong-mb") {
    base.schemaVersion = READER_EXPECTED_SCHEMA_VERSION;
    base.mergeBaseSha = WRONG_MB;
  } else {
    base.schemaVersion = 0;
    base.mergeBaseSha = MERGE;
  }
  store.set(suiteKey(REF, HEAD, BASE), base);
}

function runTool(tool: unknown): (input: unknown, ctx: unknown) => Promise<unknown> {
  return (tool as { execute: (input: unknown, ctx: unknown) => Promise<unknown> }).execute;
}

function prOctokit(): Octokit {
  const mcPass = {
    id: 1,
    body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
    created_at: "2026-10-26T05:00:00Z",
    user: { login: ME, type: "Bot" },
    performed_via_github_app: null,
  };
  const replitPass = {
    id: 2,
    body: `PASS\n${marker("replit", HEAD)}`,
    created_at: "2026-10-26T05:02:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performed_via_github_app: null,
  };
  const listComments = () => {};
  const listReviews = () => {};
  const comments = [mcPass, replitPass];
  const reviews = [
    { id: 10, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:10:00Z", commit_id: HEAD, user: { login: "cursor[bot]", type: "Bot" } },
    { id: 11, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:11:00Z", commit_id: HEAD, user: { login: "ditto-code[bot]", type: "Bot" } },
  ];
  return {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? reviews : []),
    rest: {
      pulls: {
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: HEAD },
            base: { sha: MERGE, ref: "main", repo: { owner: { login: REF.owner }, name: REF.repo } },
            draft: false,
            title: "t",
            html_url: "u",
          },
        }),
        listFiles: async () => [],
        listReviews,
      },
      issues: { listComments },
      repos: {
        getBranch: async () => ({ data: { commit: { sha: BASE } } }),
        compareCommitsWithBasehead: async () => ({
          data: { merge_base_commit: { sha: MERGE }, files: [{ filename: "docs/notes.md", status: "modified" }] },
        }),
      },
      actions: {
        listWorkflowRuns: async () => ({ data: { workflow_runs: [] } }),
        listWorkflowRunArtifacts: async () => ({ data: { artifacts: [] } }),
      },
    },
  } as unknown as Octokit;
}

function toolContext(octokit: Octokit, seed: Record<string, unknown> = {}): unknown {
  const store = new Map<string, unknown>(Object.entries(seed));
  return {
    session: { purpose: "live", continuationKey: KEY },
    host: {
      github: { getOctokit: async () => octokit },
      kv: {
        get: async (key: string) => store.get(key),
        put: async (key: string, value: unknown) => void store.set(key, value),
        delete: async (key: string) => void store.delete(key),
      },
    },
  };
}

function pairTrust(mergeBaseSha: string, rest: Record<string, unknown>): Record<string, unknown> {
  return {
    schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
    mergeBaseSha,
    checkHoldFingerprint: checkHoldFingerprint(state("mergeable")),
    ...rest,
  };
}

async function assertPostGateInvalid(variant: "v1-omit-mb" | "v2-wrong-mb" | "v3-stale-schema", label: string) {
  const w = world();
  const gate = state("mergeable");
  seedInvalidSuite(w.store, gate, variant);
  const hold = checkHoldFingerprint(gate);
  const dedupe = "MC PASS · stale dedupe";
  w.store.set(checkDedupeKey(REF, HEAD, BASE, MERGE, hold), dedupe);
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  const outcome = await postGateCheck({
    ...w.deps,
    expectedPair: deliveryPair(),
    workingCheck,
    state: gate,
    read: async () => gate,
  });
  assert.notEqual(outcome, "unchanged", `${label}: forbidden unchanged while invalid`);
  assert.equal(outcome, "posted", label);
  assert.equal(w.checks[0]?.conclusion, "action_required", label);
  assert.match(w.checks[0]?.summary ?? "", new RegExp(RECORD_VERSION_MISMATCH_DETAIL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), label);
  assert.notEqual(w.checks[0]?.conclusion, "success", label);
}

test("VR-pgc-01 V1: postGateCheck rejects omit mergeBaseSha record (not unchanged)", async () => {
  await assertPostGateInvalid("v1-omit-mb", "VR-pgc-01");
});

test("VR-pgc-02 V2: postGateCheck rejects wrong merge-base record (not unchanged)", async () => {
  await assertPostGateInvalid("v2-wrong-mb", "VR-pgc-02");
});

test("VR-pgc-03 V3: postGateCheck rejects stale schema record (not unchanged)", async () => {
  await assertPostGateInvalid("v3-stale-schema", "VR-pgc-03");
});

async function assertCarryInvalid(
  carryRecord: Record<string, unknown>,
  expectedReason: "merge-base-mismatch" | "record-version-mismatch",
  label: string,
) {
  const octokit = prOctokit();
  const result = (await runTool(compareSuiteRuns)(
    { headSha: HEAD, baseSha: MERGE, carryFromSha: OLD },
    toolContext(octokit, { [suiteKey(REF, OLD, BASE)]: carryRecord }),
  )) as Record<string, unknown>;
  assert.equal(result.recorded, false, label);
  assert.equal(result.reason, expectedReason, label);
  assert.equal(result.carried, false, label);
  assert.equal(result.clean, false, label);
  assert.notEqual(result.carried, true, `${label}: forbidden carry success`);
}

test("VR-csr-01 V1: compare_suite_runs carry omit mergeBaseSha -> merge-base-mismatch", async () => {
  await assertCarryInvalid(
    { state: "clean", at: 1, schemaVersion: READER_EXPECTED_SCHEMA_VERSION, checkHoldFingerprint: checkHoldFingerprint(state("mergeable")) },
    "merge-base-mismatch",
    "VR-csr-01",
  );
});

test("VR-csr-02 V2: compare_suite_runs carry wrong mergeBaseSha -> merge-base-mismatch", async () => {
  await assertCarryInvalid(pairTrust(WRONG_MB, { state: "clean", at: 1 }), "merge-base-mismatch", "VR-csr-02");
});

test("VR-csr-03 V3: compare_suite_runs carry stale schema -> record-version-mismatch", async () => {
  await assertCarryInvalid(
    { state: "clean", at: 1, schemaVersion: 0, mergeBaseSha: MERGE, checkHoldFingerprint: checkHoldFingerprint(state("mergeable")) },
    "record-version-mismatch",
    "VR-csr-03",
  );
});

function suiteSeed(variant: "v1-omit-mb" | "v2-wrong-mb" | "v3-stale-schema"): Record<string, unknown> {
  const gate = state("mergeable");
  const hold = checkHoldFingerprint(gate);
  if (variant === "v1-omit-mb") {
    return { state: "clean", at: 1, schemaVersion: READER_EXPECTED_SCHEMA_VERSION, checkHoldFingerprint: hold };
  }
  if (variant === "v2-wrong-mb") {
    return { state: "clean", at: 1, schemaVersion: READER_EXPECTED_SCHEMA_VERSION, mergeBaseSha: WRONG_MB, checkHoldFingerprint: hold };
  }
  return { state: "clean", at: 1, schemaVersion: 0, mergeBaseSha: MERGE, checkHoldFingerprint: hold };
}

async function assertGateToolInvalid(variant: "v1-omit-mb" | "v2-wrong-mb" | "v3-stale-schema", label: string) {
  const octokit = prOctokit();
  const result = (await runTool(checkGateState)(
    {},
    toolContext(octokit, { [suiteKey(REF, HEAD, BASE)]: suiteSeed(variant) }),
  )) as Record<string, unknown>;
  assert.equal(result.baseAvailable, true, label);
  assert.equal(result.next, "run_suite", label);
  assert.notEqual(result.next, "mergeable", `${label}: forbidden mergeable green`);
  assert.ok(result.suite !== "clean" && result.suite !== "carried", `${label}: suite not clean/carried`);
  assert.equal((result as { ok?: unknown }).ok, undefined, `${label}: no invented ok field`);
  assert.equal(typeof result.headSha, "string", label);
}

test("VR-tool-01 V1: check_gate_state omit mergeBaseSha on record", async () => {
  await assertGateToolInvalid("v1-omit-mb", "VR-tool-01");
});

test("VR-tool-02 V2: check_gate_state wrong merge base on record", async () => {
  await assertGateToolInvalid("v2-wrong-mb", "VR-tool-02");
});

test("VR-tool-03 V3: check_gate_state stale schema on record", async () => {
  await assertGateToolInvalid("v3-stale-schema", "VR-tool-03");
});
