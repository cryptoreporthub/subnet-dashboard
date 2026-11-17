/**
 * Fix-4 acceptance matrix B tranche 2 (VR-psr / VR-rgs × V1–V3).
 * Authorities: plan-1522-fix4-three-task-gated Task 1; contracts integrated §11.
 */
import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import { advanceGate, type GateDeps } from "../bot/lib/advance.js";
import { checkHoldFingerprint } from "../bot/lib/gate.js";
import { readGateState, suiteKey } from "../bot/lib/gh.js";
import { READER_EXPECTED_SCHEMA_VERSION, RECORD_VERSION_MISMATCH_DETAIL } from "../bot/lib/pair-record.js";
import { marker } from "../bot/lib/verdicts.js";
import type { RunnerReader } from "../bot/lib/runner.js";

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const BASE = "e".repeat(40);
const WRONG_MB = "f".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const ME = "simi-revision[bot]";

type RecordVariant = "v1-omit-mb" | "v2-wrong-mb" | "v3-stale-schema";

function pairTrust(mergeBaseSha: string, rest: Record<string, unknown>): Record<string, unknown> {
  return {
    schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
    mergeBaseSha,
    checkHoldFingerprint: checkHoldFingerprint({
      headSha: HEAD,
      mc: "PASS",
      cursor: "PASS",
      ditto: "PASS",
      replit: "PASS",
      suite: "clean",
      replitTagged: true,
      next: "mergeable",
    }),
    ...rest,
  };
}

function invalidRecord(variant: RecordVariant): Record<string, unknown> {
  const hold = checkHoldFingerprint({
    headSha: HEAD,
    mc: "PASS",
    cursor: "PASS",
    ditto: "PASS",
    replit: "PASS",
    suite: "clean",
    replitTagged: true,
    next: "mergeable",
  });
  if (variant === "v1-omit-mb") {
    return { state: "clean", at: 1, schemaVersion: READER_EXPECTED_SCHEMA_VERSION, checkHoldFingerprint: hold };
  }
  if (variant === "v2-wrong-mb") {
    return {
      state: "clean",
      at: 1,
      schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
      mergeBaseSha: WRONG_MB,
      checkHoldFingerprint: hold,
    };
  }
  return { state: "clean", at: 1, schemaVersion: 0, mergeBaseSha: BASE, checkHoldFingerprint: hold };
}

function racingKv(store: Map<string, unknown>, pairKey: string, valid: unknown, invalid: unknown): HostKvApi {
  let pairGets = 0;
  return {
    get: async (key: string) => {
      if (key === pairKey) {
        pairGets += 1;
        return pairGets === 1 ? valid : invalid;
      }
      return store.get(key);
    },
    put: async (key: string, value: unknown) => void store.set(key, value),
    delete: async (key: string) => void store.delete(key),
  } as unknown as HostKvApi;
}

const mcPass = {
  id: 1,
  body: `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``,
  created_at: "2026-10-26T05:00:00Z",
  user: { login: ME, type: "Bot" },
  performed_via_github_app: null,
};

const replitTagComment = {
  id: 2,
  body: `@replit review\n${marker("replit", HEAD)}`,
  created_at: "2026-10-26T05:01:00Z",
  user: { login: ME, type: "Bot" },
  performed_via_github_app: null,
};

const botReviews = [
  { id: 10, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:10:00Z", commit_id: HEAD, user: { login: "cursor[bot]", type: "Bot" } },
  { id: 11, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:11:00Z", commit_id: HEAD, user: { login: "ditto-code[bot]", type: "Bot" } },
];

function gateWorld(comments: typeof mcPass[]) {
  const posted: string[] = [];
  const store = new Map<string, unknown>();
  const listComments = () => {};
  const listReviews = () => {};
  const baseRepo = { owner: { login: REF.owner }, name: REF.repo };
  const octokit = {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? botReviews : []),
    rest: {
      pulls: {
        get: async () => ({
          data: { number: REF.number, head: { sha: HEAD }, base: { sha: BASE, ref: "main", repo: baseRepo }, draft: false },
        }),
        listReviews,
      },
      repos: {
        compareCommitsWithBasehead: async () => ({
          data: { merge_base_commit: { sha: BASE }, files: [] },
        }),
        getBranch: async () => ({ data: { commit: { sha: BASE } } }),
      },
      issues: {
        listComments,
        createComment: async ({ body }: { body: string }) => {
          posted.push(body);
          return { data: { id: posted.length } };
        },
      },
      actions: {
        listWorkflowRuns: async () => ({ data: { workflow_runs: [] } }),
        listWorkflowRunArtifacts: async () => ({ data: { artifacts: [] } }),
      },
    },
  } as unknown as Octokit;

  const reader: RunnerReader = {
    runsForSha: async () => [],
    artifactsForRun: async () => [],
    artifactZip: async () => new Uint8Array(),
  };

  const deps: GateDeps = {
    octokit,
    kv: {
      get: async (key) => store.get(key) as never,
      put: async (key, value) => void store.set(key, value),
      delete: async (key) => void store.delete(key),
    },
    mcp: {
      names: () => ["replit"],
      listTools: async () => [{ name: "ask_question" }],
      callTool: async () => ({ isError: false, content: [{ type: "text", text: "ok" }] }),
    } as unknown as HostMcpRegistry,
    ref: REF,
    createCheck: async () => ({
      update: async () => {},
      conclude: async () => {},
    }),
    reader,
  };
  return { deps, store, posted };
}

async function assertPsrRace(
  label: string,
  variant: RecordVariant,
  gatePath: "tag_replit" | "await_replit",
) {
  const comments = gatePath === "tag_replit" ? [mcPass] : [mcPass, replitTagComment];
  const { deps, store } = gateWorld(comments);
  const pairKey = suiteKey(REF, HEAD, BASE);
  const validClean = pairTrust(BASE, { state: "clean", at: 1 });
  deps.kv = racingKv(store, pairKey, validClean, invalidRecord(variant));
  const delivery = await advanceGate(deps);
  if (gatePath === "tag_replit") {
    assert.equal(delivery.taggedReplit, "skipped:stale-pair", label);
  } else {
    assert.equal(delivery.taggedReplit, "skipped", `${label}: tag already on PR`);
    assert.equal(delivery.replitAsk, "skipped:stale-pair", label);
  }
  assert.notEqual(delivery.suite, "recorded", `${label}: runSuiteIfDue not reached`);
  assert.equal(delivery.next === "tag_replit" || delivery.next === "await_replit", true, label);
}

test("VR-psr-01 V1: delivery two-read race, tag_replit, omit mergeBaseSha on second trusted read", async () => {
  await assertPsrRace("VR-psr-01", "v1-omit-mb", "tag_replit");
});

test("VR-psr-02 V2: delivery two-read race, await_replit, wrong mergeBaseSha on second read", async () => {
  await assertPsrRace("VR-psr-02", "v2-wrong-mb", "await_replit");
});

test("VR-psr-03 V3: delivery two-read race, tag_replit, stale schema on second read", async () => {
  await assertPsrRace("VR-psr-03", "v3-stale-schema", "tag_replit");
});

function rgsOctokit(comments: (typeof mcPass)[]): Octokit {
  const listComments = () => {};
  const listReviews = () => {};
  const baseRepo = { owner: { login: REF.owner }, name: REF.repo };
  return {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? botReviews : []),
    rest: {
      pulls: {
        get: async () => ({
          data: { number: REF.number, head: { sha: HEAD }, base: { sha: BASE, ref: "main", repo: baseRepo }, draft: false, title: "t", html_url: "u" },
        }),
        listFiles: async () => [],
        listReviews,
      },
      issues: { listComments },
      repos: {
        getBranch: async () => ({ data: { commit: { sha: BASE } } }),
        compareCommitsWithBasehead: async () => ({
          data: { merge_base_commit: { sha: BASE }, files: [] },
        }),
      },
    },
  } as unknown as Octokit;
}

async function assertRgs(variant: RecordVariant, suiteDetailExpected: string, label: string) {
  const store = new Map<string, unknown>();
  store.set(suiteKey(REF, HEAD, BASE), invalidRecord(variant));
  const kv = {
    get: async (key: string) => store.get(key),
    put: async (key: string, value: unknown) => void store.set(key, value),
    delete: async (key: string) => void store.delete(key),
  } as unknown as HostKvApi;
  const state = await readGateState({
    octokit: rgsOctokit([mcPass]),
    kv,
    ref: REF,
    headSha: HEAD,
  });
  assert.equal(state.next, "run_suite", label);
  assert.ok(state.suite !== "clean" && state.suite !== "carried", label);
  assert.equal(state.suiteDetail, suiteDetailExpected, label);
  assert.notEqual(state.next, "mergeable", `${label}: forbidden mergeable green`);
}

test("VR-rgs-01 V1: readGateState omit mergeBaseSha", async () => {
  await assertRgs("v1-omit-mb", `${RECORD_VERSION_MISMATCH_DETAIL} · merge-base-mismatch`, "VR-rgs-01");
});

test("VR-rgs-02 V2: readGateState wrong mergeBaseSha", async () => {
  await assertRgs("v2-wrong-mb", `${RECORD_VERSION_MISMATCH_DETAIL} · merge-base-mismatch`, "VR-rgs-02");
});

test("VR-rgs-03 V3: readGateState stale schemaVersion", async () => {
  await assertRgs("v3-stale-schema", RECORD_VERSION_MISMATCH_DETAIL, "VR-rgs-03");
});
