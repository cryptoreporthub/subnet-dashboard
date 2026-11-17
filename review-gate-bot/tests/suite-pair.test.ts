import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import {
  pullRequestReviewTurn,
  pushToBaseBranch,
  type GateDeps,
} from "../bot/lib/advance.js";
import { CHECK_NAME, postGateCheck } from "../bot/lib/check.js";
import { checkHoldFingerprint, prKey, reviewTurnKey, type GateState } from "../bot/lib/gate.js";
import { GATE_HEAD_CHANGED_DETAIL, legacySuiteKey, readGateState, readSuiteRecord, suiteKey } from "../bot/lib/gh.js";
import { recordSuiteComparison, runSuiteIfDue } from "../bot/lib/suite-record.js";
import { marker } from "../bot/lib/verdicts.js";
import { JUNIT_ARTIFACT, type RunnerReader } from "../bot/lib/runner.js";
import type { RecordedSuite } from "../bot/lib/gh.js";
import { READER_EXPECTED_SCHEMA_VERSION } from "../bot/lib/pair-record.js";

/** Pair-key kv shape trusted by readSuiteRecordTrusted (mergeBaseSha must match live observePair). */
function pairTrust(mergeBaseSha: string, rest: Partial<RecordedSuite> & { state: RecordedSuite["state"] }): RecordedSuite {
  const { checkHoldFingerprint: fpOverride, ...body } = rest;
  return {
    schemaVersion: READER_EXPECTED_SCHEMA_VERSION,
    mergeBaseSha,
    checkHoldFingerprint: fpOverride ?? checkHoldFingerprint(freshGateState()),
    ...body,
  };
}

function freshGateState(): GateState {
  return {
    headSha: HEAD,
    mc: "PASS",
    cursor: "PASS",
    ditto: "PASS",
    replit: "PASS",
    suite: "clean",
    replitTagged: true,
    next: "mergeable",
  };
}

const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };
const HEAD = "c".repeat(40);
const HEAD_LIVE = "f".repeat(40);
const BASE_A = "a".repeat(40);
const BASE_B = "b".repeat(40);
const TIP_D = "d".repeat(40);
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
  live: { head: string; base: string | undefined; tip?: string };
  posted: string[];
  checks: Array<{ conclusion?: string; summary?: string }>;
  octokit: Octokit;
};

function world(options: { seed?: Record<string, unknown>; comments?: object[]; reviews?: object[]; mergeBaseMissing?: boolean } = {}): World {
  const posted: string[] = [];
  const checks: World["checks"] = [];
  const live = { head: HEAD, base: BASE_A as string | undefined, tip: BASE_A as string | undefined };
  const comments = [...(options.comments ?? [])];
  const listComments = () => {};
  const listReviews = () => {};
  const baseRepo = { owner: { login: REF.owner }, name: REF.repo };
  const octokit = {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? (options.reviews ?? []) : []),
    rest: {
      pulls: {
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: live.head },
            base: live.base === undefined ? {} : { sha: live.base, ref: "main", repo: baseRepo },
            draft: false,
          },
        }),
        list: async () => ({ data: [] }),
        listReviews,
      },
      repos: {
        compareCommitsWithBasehead: async () => ({
          data: {
            merge_base_commit: options.mergeBaseMissing ? null : { sha: live.base },
            files: [],
          },
        }),
        getBranch: async () => ({
          data: { commit: { sha: live.tip ?? live.base } },
        }),
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
      update: async (patch: { status?: string }) => {
        if (patch.status === "in_progress") {
          checks.push({ conclusion: undefined, summary: "in_progress" });
        }
      },
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

test("ditto r4486944691: recordSuiteComparison rejects caller pair that disagrees with live read", async () => {
  const w = world();
  const outcome = await recordSuiteComparison({
    octokit: {
      ...w.octokit,
      rest: {
        ...w.octokit.rest,
        pulls: {
          ...w.octokit.rest.pulls,
          get: async () => ({
            data: {
              number: REF.number,
              head: { sha: HEAD_LIVE },
              base: { sha: BASE_A, ref: "main", repo: { owner: { login: REF.owner }, name: REF.repo } },
              draft: false,
            },
          }),
        },
      },
    } as unknown as Octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: BASE_A,
    reader: reader(),
  });
  assert.equal(outcome.ok, false);
  assert.equal(!outcome.ok && outcome.reason, "stale-pair");
  assert.equal(w.store.has(suiteKey(REF, HEAD, BASE_A)), false);
  assert.equal(w.store.has(suiteKey(REF, HEAD_LIVE, BASE_A)), false);
});

test("ditto r4486944691: runSuiteIfDue returns stale-pair when caller pair disagrees with live read", async () => {
  const w = world({ comments: [mcPass], reviews: botReviews });
  const octokit = {
    ...w.octokit,
    rest: {
      ...w.octokit.rest,
      pulls: {
        ...w.octokit.rest.pulls,
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: HEAD_LIVE },
            base: { sha: BASE_A, ref: "main", repo: { owner: { login: REF.owner }, name: REF.repo } },
            draft: false,
          },
        }),
      },
    },
  } as unknown as Octokit;
  const label = await runSuiteIfDue({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: BASE_A,
    reader: reader(),
  });
  assert.equal(label, "stale-pair");
  assert.equal(w.store.has(suiteKey(REF, HEAD, BASE_A)), false);
  assert.equal(w.store.has(suiteKey(REF, HEAD_LIVE, BASE_A)), false);
});

test("ditto r4486945190: readGateState is not mergeable when live PR head differs from delivery headSha", async () => {
  const replitTag = {
    id: 2,
    body: `${marker("replit", HEAD)}\n@replit review ${HEAD}`,
    created_at: "2026-10-26T05:20:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performed_via_github_app: null,
  };
  const replitPass = {
    id: 3,
    body: `Replit: **PASS** at ${HEAD}`,
    created_at: "2026-10-26T05:30:00Z",
    user: { login: "cryptoreporthub", type: "User" },
    performed_via_github_app: null,
  };
  const w = world({
    comments: [mcPass, replitTag, replitPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) },
  });
  w.live.head = HEAD_LIVE;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.notEqual(state.next, "mergeable");
  assert.equal(state.suiteDetail, GATE_HEAD_CHANGED_DETAIL);
});

test("suite keys include the PR base; a base move leaves the old pair orphaned", async () => {
  assert.notEqual(suiteKey(REF, HEAD, BASE_A), suiteKey(REF, HEAD, BASE_B));
  const w = world({ seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) } });
  w.live.base = BASE_B;
  w.live.tip = BASE_B;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
});

test("a base move re-records the suite for the new pair", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) },
  });
  w.live.base = BASE_B;
  w.live.tip = BASE_B;
  await runSuiteIfDue({ ...w.deps, headSha: HEAD, baseSha: BASE_B, baseTipSha: BASE_B, reader: reader() });
  assert.equal((w.store.get(suiteKey(REF, HEAD, BASE_B)) as { state?: string })?.state, "clean");
});

test("the same base and run id is not downloaded again", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", runId: 1, at: 1 }) },
  });
  let downloads = 0;
  const counted: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      downloads += 1;
      return zipOf(CLEAN);
    },
  };
  const label = await runSuiteIfDue({ ...w.deps, headSha: HEAD, baseSha: BASE_A, baseTipSha: BASE_A, reader: counted });
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
      [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 2 }),
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
  await w.deps.kv.put(suiteKey(REF, HEAD, BASE_A), pairTrust(BASE_A, { state: "clean", at: 2 }));
  const record = await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_A);
  assert.equal(record?.invalid, "needs-joshua");
});

test("carry against the live base uses the pair key", async () => {
  const w = world({ seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "carried", carriedFrom: HEAD, at: 1 }) } });
  assert.equal((await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_A))?.state, "carried");
  assert.equal(await readSuiteRecord(w.deps.kv, REF, HEAD, BASE_B), undefined);
});

test("undefined base omits merge-base but does not force NEEDS-JOSHUA before computeGate", async () => {
  const w = world({ comments: [mcPass], reviews: botReviews });
  w.live.base = undefined;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
  assert.equal(state.next, "run_suite");
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

test("a mergeable check is not green when the base tip moves before conclude", async () => {
  const w = world();
  w.store.set(suiteKey(REF, HEAD, BASE_A), pairTrust(BASE_A, { state: "clean", at: 1 }));
  let reads = 0;
  const octokit = {
    rest: {
      pulls: {
        get: async () => {
          reads += 1;
          return {
            data: {
              number: REF.number,
              head: { sha: HEAD },
              base: { sha: BASE_A, ref: "main", repo: { owner: { login: REF.owner }, name: REF.repo } },
              draft: false,
            },
          };
        },
      },
      repos: {
        getBranch: async () => ({
          data: { commit: { sha: reads >= 2 ? BASE_B : BASE_A } },
        }),
        compareCommitsWithBasehead: async () => ({
          data: { merge_base_commit: { sha: BASE_A }, files: [] },
        }),
      },
    },
  } as unknown as Octokit;
  const workingCheck = await w.deps.createCheck({ name: CHECK_NAME, sha: HEAD });
  await postGateCheck({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    createCheck: w.deps.createCheck,
    workingCheck,
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

test("recordSuiteComparison writes baseline-test-missing on the pair key", async () => {
  const w = world();
  let call = 0;
  const headXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="b"/></testsuite></testsuites>';
  const baseXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="a"/><testcase classname="t" name="b"/></testsuite></testsuites>';
  const r: RunnerReader = {
    ...reader(),
    artifactZip: async () => zipOf(++call === 1 ? headXml : baseXml),
  };
  await recordSuiteComparison({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD, baseSha: BASE_A, baseTipSha: BASE_A, reader: r });
  assert.equal(w.store.has(legacySuiteKey(REF, HEAD)), false);
  assert.equal((w.store.get(suiteKey(REF, HEAD, BASE_A)) as { invalid?: string })?.invalid, "baseline-test-missing");
});

test("a stale pulls base with an advanced branch tip orphans the old pair clean", async () => {
  const w = world({ seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) } });
  w.live.tip = TIP_D;
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
});

test("when the branch tip moves, the suite re-records under the tip key and compares merge-base JUnit", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) },
  });
  w.live.tip = TIP_D;
  let downloads = 0;
  const junitFor: string[] = [];
  const counted: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      downloads += 1;
      return zipOf(CLEAN);
    },
    runsForSha: async (sha) => {
      junitFor.push(sha);
      return [{ id: 1, conclusion: "success" }];
    },
  };
  const label = await runSuiteIfDue({
    ...w.deps,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: TIP_D,
    reader: counted,
  });
  assert.equal(label, "recorded");
  assert.ok(downloads > 0, "suite comparison runs again after tip moves");
  assert.ok(junitFor.includes(BASE_A), "base JUnit is read at merge-base, not tip");
  assert.equal((w.store.get(suiteKey(REF, HEAD, TIP_D)) as { state?: string })?.state, "clean");
  assert.equal(w.store.has(suiteKey(REF, HEAD, BASE_A)), true, "old tip key is orphaned, not deleted");
});

test("tip-only tests on main do not create baseline-test-missing when merge-base is compared", async () => {
  const w = world();
  w.live.tip = TIP_D;
  const headXml = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="shared"/></testsuite></testsuites>';
  const mergeBaseXml =
    '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="shared"/></testsuite></testsuites>';
  let call = 0;
  const r: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      call += 1;
      if (call === 1) {
        return zipOf(headXml);
      }
      return zipOf(mergeBaseXml);
    },
    runsForSha: async (sha) => {
      if (sha === TIP_D) {
        throw new Error("tip JUnit must not be requested");
      }
      return [{ id: 1, conclusion: "success" }];
    },
  };
  await recordSuiteComparison({
    octokit: w.octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: TIP_D,
    reader: r,
  });
  assert.equal(w.store.has(legacySuiteKey(REF, HEAD)), false);
  assert.equal((w.store.get(suiteKey(REF, HEAD, TIP_D)) as { state?: string })?.state, "clean");
});

test("a tip move between artifact read and record write returns stale-pair and writes nothing", async () => {
  const w = world();
  let afterArtifacts = false;
  const octokit = {
    rest: {
      pulls: {
        get: async () => ({
          data: {
            number: REF.number,
            head: { sha: HEAD },
            base: { sha: BASE_A, ref: "main", repo: { owner: { login: REF.owner }, name: REF.repo } },
            draft: false,
          },
        }),
      },
      repos: {
        compareCommitsWithBasehead: async () => ({ data: { merge_base_commit: { sha: BASE_A }, files: [] } }),
        getBranch: async () => ({
          data: { commit: { sha: afterArtifacts ? TIP_D : BASE_A } },
        }),
      },
    },
  } as unknown as Octokit;
  let zipCalls = 0;
  const r: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      zipCalls += 1;
      if (zipCalls >= 2) {
        afterArtifacts = true;
      }
      return zipOf(CLEAN);
    },
  };
  const outcome = await recordSuiteComparison({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: BASE_A,
    reader: r,
  });
  assert.equal(outcome.ok, false);
  assert.equal(!outcome.ok && outcome.reason, "stale-pair");
  assert.equal(w.store.has(suiteKey(REF, HEAD, BASE_A)), false);
  assert.equal(w.store.has(suiteKey(REF, HEAD, TIP_D)), false);
});

test("compareCommitsWithBasehead failure omits merge-base and blocks a stale green check", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) },
  });
  const octokit = {
    ...w.octokit,
    rest: {
      ...w.octokit.rest,
      repos: {
        ...w.octokit.rest.repos,
        compareCommitsWithBasehead: async () => {
          throw new Error("github 503");
        },
      },
    },
  } as unknown as Octokit;
  const state = await readGateState({ octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.notEqual(state.next, "mergeable");
  await postGateCheck({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    createCheck: w.deps.createCheck,
    state: { ...state, next: "mergeable" as const, suite: "clean" as const },
    read: async () => state,
  });
  assert.equal(w.checks[0]?.conclusion, "action_required");
  const summary = w.checks[0]?.summary ?? "";
  assert.ok(
    summary.includes("GitHub could not resolve") || summary.includes("compare:") || summary.includes("503"),
    `expected pair-read failure in summary: ${summary}`,
  );
});

test("a pair-key baseline-test-missing at an old tip does not block re-record at a new tip", async () => {
  const w = world({
    seed: {
      [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "regressed", invalid: "baseline-test-missing", at: 1 }),
    },
  });
  w.live.tip = TIP_D;
  let downloads = 0;
  const label = await runSuiteIfDue({
    ...w.deps,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: TIP_D,
    reader: {
      ...reader(),
      artifactZip: async () => {
        downloads += 1;
        return zipOf(CLEAN);
      },
    },
  });
  assert.equal(label, "recorded");
  assert.ok(downloads > 0);
  assert.equal((w.store.get(suiteKey(REF, HEAD, TIP_D)) as { state?: string })?.state, "clean");
});

test("unavailable merge-base refuses recordComparison without downloading JUnit", async () => {
  const w = world({ mergeBaseMissing: true });
  let downloads = 0;
  const outcome = await recordSuiteComparison({
    octokit: w.octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: BASE_A,
    baseTipSha: BASE_A,
    reader: {
      ...reader(),
      artifactZip: async () => {
        downloads += 1;
        return zipOf(CLEAN);
      },
    },
  });
  assert.equal(outcome.ok, false);
  assert.equal(!outcome.ok && outcome.reason, "base-unavailable");
  assert.equal(downloads, 0);
});

test("amended6 B: seeded pair clean ignored when merge-base lookup is empty", async () => {
  const w = world({
    comments: [mcPass],
    reviews: botReviews,
    seed: { [suiteKey(REF, HEAD, BASE_A)]: pairTrust(BASE_A, { state: "clean", at: 1 }) },
    mergeBaseMissing: true,
  });
  const state = await readGateState({ octokit: w.octokit, kv: w.deps.kv, ref: REF, headSha: HEAD });
  assert.equal(state.suite, "missing");
  assert.notEqual(state.next, "mergeable");
  await postGateCheck({
    ...w.deps,
    state: { ...state, next: "mergeable" as const, suite: "clean" as const },
    read: async () => state,
  });
  assert.equal(w.checks[0]?.conclusion, "action_required");
});

test("amended6 C: empty merge_base_commit never downloads tip JUnit", async () => {
  const MERGE_M = "e".repeat(40);
  const TIP_T = TIP_D;
  let downloads = 0;
  const failAtTip = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="t" name="fail"/></testsuite></testsuites>';
  const w = world({ mergeBaseMissing: true });
  w.live.tip = TIP_T;
  w.live.base = MERGE_M;
  const octokit = {
    ...w.octokit,
    rest: {
      ...w.octokit.rest,
      repos: {
        ...w.octokit.rest.repos,
        compareCommitsWithBasehead: async () => ({ data: { merge_base_commit: null, files: [] } }),
      },
    },
  } as unknown as Octokit;
  const r: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      downloads += 1;
      return zipOf(CLEAN);
    },
  };
  const outcome = await recordSuiteComparison({
    octokit,
    kv: w.deps.kv,
    ref: REF,
    headSha: HEAD,
    baseSha: MERGE_M,
    baseTipSha: TIP_T,
    reader: r,
  });
  assert.equal(outcome.ok, false);
  assert.equal(downloads, 0);
  assert.equal(w.store.has(suiteKey(REF, HEAD, TIP_T)), false);
});

test("amended6 E: runSuiteIfDue opens in_progress check before artifact download", async () => {
  const w = world({ comments: [mcPass], reviews: botReviews });
  let downloads = 0;
  let resolveDownload: (() => void) | undefined;
  const downloadGate = new Promise<void>((resolve) => {
    resolveDownload = resolve;
  });
  const slow: RunnerReader = {
    ...reader(),
    artifactZip: async () => {
      downloads += 1;
      await downloadGate;
      return zipOf(CLEAN);
    },
  };
  w.deps.reader = slow;
  const advancePromise = pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(w.checks.some((c) => c.summary === "in-progress" || c.conclusion === undefined));
  resolveDownload?.();
  await advancePromise;
  assert.ok(downloads > 0);
  assert.ok(w.checks.some((c) => c.conclusion === "action_required" || c.conclusion === "success"));
});
