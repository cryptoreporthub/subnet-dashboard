import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import {
  pullRequestReviewTurn,
  pushToBaseBranch,
  type GateDeps,
} from "../bot/lib/advance.js";
import { postGateCheck } from "../bot/lib/check.js";
import { prKey, reviewTurnKey } from "../bot/lib/gate.js";
import { legacySuiteKey, readGateState, readSuiteRecord, suiteKey } from "../bot/lib/gh.js";
import { recordSuiteComparison, runSuiteIfDue } from "../bot/lib/suite-record.js";
import { marker } from "../bot/lib/verdicts.js";
import { JUNIT_ARTIFACT, type RunnerReader } from "../bot/lib/runner.js";

const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const HEAD = "c".repeat(40);
const BASE_A = "a".repeat(40);
const BASE_B = "b".repeat(40);
const ME = "simi-revision[bot]";
const CLEAN = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="a"/></testsuite></testsuites>';

function zipOf(text: string): Uint8Array {
  const name = Buffer.from("pytest.xml");
  const data = Buffer.from(text, "utf8");
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt32LE(data.length, 18);
  local.writeUInt32LE(data.length, 22);
  local.writeUInt16LE(name.length, 26);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt32LE(data.length, 20);
  central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(name.length, 28);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(central.length + name.length, 12);
  end.writeUInt32LE(local.length + name.length + data.length, 16);
  return new Uint8Array(Buffer.concat([local, name, data, central, name, end]));
}

function reader(): RunnerReader {
  return {
    runsForSha: async () => [{ id: 1, conclusion: "success" }],
    artifactsForRun: async () => [{ id: 2, name: JUNIT_ARTIFACT }],
    artifactZip: async () => zipOf(CLEAN),
  };
}

type World = {
  deps: GateDeps;
  store: Map<string, unknown>;
  live: { head: string; base: string | undefined };
  posted: string[];
  checks: Array<{ conclusion?: string; summary?: string }>;
  octokit: Octokit;
};

function world(options: { seed?: Record<string, unknown>; comments?: object[]; reviews?: object[] } = {}): World {
  const posted: string[] = [];
  const checks: World["checks"] = [];
  const live = { head: HEAD, base: BASE_A as string | undefined };
  const comments = [...(options.comments ?? [])];
  const listComments = () => {};
  const listReviews = () => {};
  const octokit = {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? (options.reviews ?? []) : []),
    rest: {
      pulls: {
        get: async () => ({ data: { head: { sha: live.head }, base: live.base === undefined ? {} : { sha: live.base }, draft: false } }),
        list: async () => ({ data: [] }),
        listReviews,
      },
      repos: {
        compareCommitsWithBasehead: async () => ({ data: { files: [] } }),
      },
      issues: {
        listComments,
        createComment: async ({ body }: { body: string }) => {
          posted.push(body);
          return { data: { id: posted.length } };
        },
      },
    },
  } as unknown as Octokit;
  const store = new Map<string, unknown>(Object.entries(options.seed ?? {}));
  const deps: GateDeps = {
    octokit,
    kv: {
      get: async (key) => store.get(key) as never,
      put: async (key, value) => void store.set(key, value),
      delete: async (key) => void store.delete(key),
    },
    mcp: { names: () => [], listTools: async () => [], callTool: async () => ({ isError: true, content: [] }) } as GateDeps["mcp"],
    ref: REF,
    createCheck: async () => ({
      update: async () => {},
      conclude: async (done: { conclusion: string; output?: { summary: string } }) => {
        checks.push({ conclusion: done.conclusion, summary: done.output?.summary });
      },
    }),
  };
  return { deps, store, live, posted, checks, octokit };
}

const mcPass = {
  id: 1,
  body: `${marker("mc-verdict", HEAD)}\nMC: **PASS**`,
  created_at: "2026-10-26T05:00:00Z",
  user: { login: ME, type: "Bot" },
  performed_via_github_app: null,
};

const botReviews = [
  { id: 10, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:10:00Z", commit_id: HEAD, user: { login: "cursor[bot]", type: "Bot" } },
  { id: 11, body: "", state: "APPROVED", submitted_at: "2026-10-26T05:11:00Z", commit_id: HEAD, user: { login: "ditto-code[bot]", type: "Bot" } },
];

test("suite keys include the PR base; a base move leaves the old pair orphaned", async () => {
  assert.notEqual(suiteKey(REF, HEAD, BASE_A), suiteKey(REF, HEAD, BASE_B));
  const w = world({ seed: { [suiteKey(REF, HEAD, BASE_A)]: { state: "clean", at: 1 } } });
  w.live.base = BASE_B;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
});

test("a base move re-records the suite for the new pair", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: { state: "clean", at: 1 } },
  });
  w.live.base = BASE_B;
  await runSuiteIfDue({ ...w.deps, headSha: HEAD, baseSha: BASE_B, reader: reader() });
  assert.equal((w.store.get(suiteKey(REF, HEAD, BASE_B)) as { state?: string })?.state, "clean");
});

test("the same base and run id is not downloaded again", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: { state: "clean", runId: 1, at: 1 } },
  });
  let downloads = 0;
  const counted: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      downloads += 1;
      return zipOf(CLEAN);
    },
  };
  const label = await runSuiteIfDue({ ...w.deps, headSha: HEAD, baseSha: BASE_A, reader: counted });
  assert.equal(label, "already-recorded");
  assert.equal(downloads, 0);
});

test("legacy head-only clean does not satisfy a new base", async () => {
  const w = world({ seed: { [legacySuiteKey(REF, HEAD)]: { state: "clean", at: 1 } } });
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
});

test("legacy head-only NEEDS-JOSHUA still blocks the gate", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: {
      [legacySuiteKey(REF, HEAD)]: { state: "regressed", invalid: "needs-joshua", detail: "pytest.ini", at: 1 },
      [suiteKey(REF, HEAD, BASE_A)]: { state: "clean", at: 2 },
    },
  });
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.next, "needs_joshua");
});

test("pull_request edited with a base change advances the gate without a review lease", async () => {
  const w = world({ comments: [mcPass], reviews: botReviews });
  const lease = await pullRequestReviewTurn(w.deps, { action: "edited", draft: false, changes: { base: { sha: BASE_B } } });
  assert.equal(lease, undefined);
  assert.equal(w.store.has(reviewTurnKey(REF, HEAD)), false);
  assert.ok(w.checks.length >= 1);
});

test("a late pair-clean write cannot clear a head NEEDS-JOSHUA hold", async () => {
  const w = world({
    seed: { [legacySuiteKey(REF, HEAD)]: { state: "regressed", invalid: "needs-joshua", detail: "x", at: 1 } },
  });
  await w.deps.kv.put(suiteKey(REF, HEAD, BASE_A), { state: "clean", at: 2 });
  const record = await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_A);
  assert.equal(record?.invalid, "needs-joshua");
});

test("carry against the live base uses the pair key", async () => {
  const w = world({ seed: { [suiteKey(REF, HEAD, BASE_A)]: { state: "carried", carriedFrom: HEAD, at: 1 } } });
  assert.equal((await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_A))?.state, "carried");
  assert.equal(await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_B), undefined);
});

test("undefined base reads as NEEDS-JOSHUA", async () => {
  const w = world({ comments: [mcPass], reviews: botReviews });
  w.live.base = undefined;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "needs-joshua");
  assert.equal(state.next, "needs_joshua");
});

test("push to the PR base reconciles open pull requests", async () => {
  const w = world({ comments: [mcPass] });
  (w.octokit as { paginate: (fn: unknown) => Promise<unknown[]> }).paginate = async (fn: unknown) => {
    if (fn === w.octokit.rest.pulls.list) {
      return [{ number: REF.number }];
    }
    return [];
  };
  await pushToBaseBranch(w.deps, { ref: "refs/heads/main" });
  assert.ok(w.checks.length >= 1);
});

test("a mergeable check is not green when the base moves before conclude", async () => {
  const w = world();
  w.store.set(suiteKey(REF, HEAD, BASE_A), { state: "clean", at: 1 });
  let reads = 0;
  const octokit = {
    rest: {
      pulls: {
        get: async () => {
          reads += 1;
          const baseSha = reads >= 2 ? BASE_B : BASE_A;
          return { data: { head: { sha: HEAD }, base: { sha: baseSha } } };
        },
      },
    },
  } as unknown as Octokit;
  await postGateCheck({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    createCheck: w.deps.createCheck,
    state: {
      headSha: HEAD,
      mc: "PASS",
      cursor: "PASS",
      ditto: "PASS",
      replit: "PASS",
      suite: "clean",
      replitTagged: true,
      next: "mergeable",
    },
    read: async () => ({
      headSha: HEAD,
      mc: "PASS",
      cursor: "PASS",
      ditto: "PASS",
      replit: "PASS",
      suite: "clean",
      replitTagged: true,
      next: "mergeable",
    }),
  });
  assert.equal(w.checks[0]?.conclusion, "cancelled");
});

test("recordSuiteComparison writes baseline-test-missing on the head-only key", async () => {
  const w = world();
  let call = 0;
  const headXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="b"/></testsuite></testsuites>';
  const baseXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="a"/><testcase classname="t" name="b"/></testsuite></testsuites>';
  const r: RunnerReader = {
    ...reader(),
    artifactZip: async () => zipOf(++call === 1 ? headXml : baseXml),
  };
  await recordSuiteComparison({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD, baseSha: BASE_A, reader: r });
  assert.ok(w.store.has(legacySuiteKey(REF, HEAD)));
  assert.equal(w.store.has(suiteKey(REF, HEAD, BASE_A)), false);
});
