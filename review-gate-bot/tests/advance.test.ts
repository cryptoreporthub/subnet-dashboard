import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import { advanceGate, commentReviewTurn, commentTurn, failureReleasesLease, logAsk, pullRequestReviewTurn, pullRequestTurn, releaseReviewTurnIfHolder, reviewEventTurn, reviewLeaseFromState, type GateDeps } from "../bot/lib/advance.js";
import { suiteKey } from "../bot/lib/gh.js";
import { prKey, replitAskKey, replitTagKey, reviewTurnKey } from "../bot/lib/gate.js";
import { LEASE_MS, leaseToken, releaseLeaseIfHolder } from "../bot/lib/lock.js";
import { marker } from "../bot/lib/verdicts.js";
import { JUNIT_ARTIFACT, type RunnerReader } from "../bot/lib/runner.js";
import { deflateRawSync } from "node:zlib";

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const OTHER = "1234567890abcdef1234567890abcdef12345678";
const NEW_HEAD = "d".repeat(40);
const BASE = "e".repeat(40);
const ME = "simi-revision[bot]";
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

type Raw = {
  id: number;
  body: string;
  created_at: string;
  user: { login: string; type: string };
  performed_via_github_app: { id?: number; slug: string } | null;
};

type CheckCall = { name: string; sha: string; conclusion?: string; summary?: string };

/** One PR as GitHub shows it. The bot posts as its own App, `ME`. */
function world(
  options: {
    draft?: boolean;
    comments?: Raw[];
    reviews?: object[];
    seed?: Record<string, unknown>;
    createFails?: boolean;
    checkFails?: boolean;
    changedFiles?: string[];
  } = {},
) {
  const comments = [...(options.comments ?? [])];
  const posted: string[] = [];
  const checks: CheckCall[] = [];
  const listComments = () => {};
  const listReviews = () => {};
  const live = { head: HEAD };
  const octokit = {
    paginate: async (fn: unknown) => (fn === listComments ? comments : fn === listReviews ? (options.reviews ?? []) : []),
    rest: {
      pulls: {
        get: async () => ({ data: { head: { sha: live.head }, base: { sha: BASE }, draft: options.draft ?? false } }),
        listReviews,
      },
      repos: {
        compareCommitsWithBasehead: async () => ({ data: { files: (options.changedFiles ?? []).map((filename) => ({ filename, status: "modified" })) } }),
      },
      issues: {
        listComments,
        createComment: async ({ body }: { body: string }) => {
          if (options.createFails === true) {
            throw new Error("github 502");
          }
          const id = 1000 + posted.length;
          posted.push(body);
          comments.push({
            id,
            body,
            created_at: "2026-10-26T06:00:00Z",
            user: { login: ME, type: "Bot" },
            performed_via_github_app: null,
          });
          return { data: { id } };
        },
      },
    },
  } as unknown as Octokit;

  const store = new Map<string, unknown>(Object.entries(options.seed ?? {}));
  let asks = 0;
  const deps: GateDeps = {
    octokit,
    kv: {
      get: async (key) => store.get(key) as never,
      put: async (key, value) => {
        store.set(key, value);
      },
      delete: async (key) => {
        store.delete(key);
      },
    },
    mcp: {
      names: () => ["replit"],
      listTools: async () => [{ name: "ask_question" }],
      callTool: async () => {
        asks += 1;
        return { isError: false, content: [{ type: "text", text: "ok" }] };
      },
    } as unknown as HostMcpRegistry,
    ref: REF,
    createCheck: async (input) => {
      if (options.checkFails === true) {
        throw new Error("github 403");
      }
      const call: CheckCall = { name: input.name, sha: input.sha };
      checks.push(call);
      return {
        update: async () => {},
        conclude: async ({ conclusion, output }) => {
          call.conclusion = conclusion;
          call.summary = output?.summary;
        },
      };
    },
  };
  return { deps, posted, comments, checks, store, asks: () => asks, live };
}

const mcPass: Raw = {
  id: 1,
  body: `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``,
  created_at: "2026-10-26T05:00:00Z",
  user: { login: ME, type: "Bot" },
  performed_via_github_app: null,
};

test("a PR that is a draft right now starts no turn and posts nothing, whatever the payload says", async () => {
  const w = world({ draft: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "synchronize", draft: false }), false);
  assert.deepEqual(w.posted, []);
});

test("a reopened PR whose head already has an MC verdict starts no second review", async () => {
  const w = world({ comments: [mcPass] });
  assert.equal(await pullRequestTurn(w.deps, { action: "reopened", draft: false }), false);
});

test("a PR with no MC verdict yet starts a review turn and tags Cursor and Ditto once", async () => {
  const w = world();
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
  assert.equal(await pullRequestTurn(w.deps, { action: "synchronize", draft: false }), false, "a duplicate for this head starts no second turn");
  assert.equal(w.posted.length, 1);
  assert.ok(w.posted[0]?.includes("@cursor review"));
});

test("the bot's own comments do not re-enter the gate", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  assert.equal(w.posted.length, 1);
  const own = w.comments[w.comments.length - 1];
  assert.equal(await commentTurn(w.deps, own?.user.login), false, "its own tag must not start a second turn");
});

test("another author's comment starts the review turn while MC is missing", async () => {
  assert.equal(await commentTurn(world().deps, "some-reviewer"), true);
});

test("a comment from the bare name 'simi-revision' is just a person", async () => {
  const w = world();
  assert.equal(await commentTurn(w.deps, "simi-revision"), true);
});

test("a comment from the owner's account is never the bot's, even one that carries a marker", async () => {
  assert.equal(await commentTurn(world().deps, "cryptoreporthub"), true, "the owner account is shared, so it still runs the gate");
});

function simibotPass(appId: number): Raw {
  return {
    id: 2,
    body: `MC: **PASS** at \`${HEAD}\`\n<!-- mc-verdict:${HEAD} -->`,
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "simibot[bot]", type: "Bot" },
    performed_via_github_app: { id: appId, slug: "simibot" },
  };
}

test("simibot's PASS from its App (id 5501340) is the MC verdict, so no second review starts", async () => {
  const w = world({ comments: [simibotPass(5501340)] });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), false);
});

test("a PASS named simibot from another App id does not count, so the review turn still starts", async () => {
  const w = world({ comments: [simibotPass(1236702)] });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
});

test("a failing tag post on a pull_request event does not lose the review turn", async () => {
  const w = world({ createFails: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
});

// --- The review-gate check run ------------------------------------------------

test("a head still waiting on reviewers gets an action_required review-gate check, never a passing one", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  assert.deepEqual(w.checks.map(({ name, sha, conclusion }) => ({ name, sha, conclusion })), [{ name: "review-gate", sha: HEAD, conclusion: "action_required" }]);
});

test("a FAIL anywhere at the head posts a failing review-gate check", async () => {
  const w = world({ comments: [{ ...mcPass, body: `${marker("mc-verdict", HEAD)}\nMC: **FAIL** at \`${HEAD}\`` }] });
  await reviewEventTurn(w.deps);
  assert.equal(w.checks[0]?.conclusion, "failure");
});

test("the same gate state at the same head posts its check once, not once per webhook", async () => {
  const w = world();
  await reviewEventTurn(w.deps);
  await reviewEventTurn(w.deps);
  await reviewEventTurn(w.deps);
  assert.equal(w.checks.length, 1);
});

const CLEAN_JUNIT = '<?xml version="1.0"?><testsuites><testsuite name="pytest"><testcase classname="tests.test_x" name="a"/></testsuite></testsuites>';

/** A stored (uncompressed) zip with one file, which is all the artifact reader needs. */
function zipOf(name: string, text: string): Uint8Array {
  const nameBytes = Buffer.from(name, "utf8");
  const data = Buffer.from(text, "utf8");
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt16LE(0, 8);
  local.writeUInt32LE(data.length, 18);
  local.writeUInt32LE(data.length, 22);
  local.writeUInt16LE(nameBytes.length, 26);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(0, 10);
  central.writeUInt32LE(data.length, 20);
  central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(nameBytes.length, 28);
  central.writeUInt32LE(0, 42);
  const directoryLength = central.length + nameBytes.length;
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(directoryLength, 12);
  end.writeUInt32LE(local.length + nameBytes.length + data.length, 16);
  return new Uint8Array(Buffer.concat([local, nameBytes, data, central, nameBytes, end]));
}

/** An Actions reader that serves one finished run per SHA, and counts the artifact downloads. */
function suiteReader(options: { runId?: number; junit?: string } = {}) {
  const downloads = { count: 0 };
  const reader: RunnerReader = {
    runsForSha: async () => (options.runId === undefined ? [] : [{ id: options.runId, conclusion: "success" }]),
    artifactsForRun: async () => [{ id: 5, name: JUNIT_ARTIFACT }],
    artifactZip: async () => {
      downloads.count += 1;
      return zipOf("pytest.xml", options.junit ?? CLEAN_JUNIT);
    },
  };
  return { reader, downloads };
}

test("the gate runs the suite itself when it is due: it records a clean result and tags Replit in the same delivery", async () => {
  const w = world({ comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
  const { reader } = suiteReader({ runId: 77 });
  await reviewEventTurn({ ...w.deps, reader });
  const record = w.store.get(suiteKey(REF, HEAD)) as { state?: string; runId?: number } | undefined;
  assert.equal(record?.state, "clean");
  assert.equal(record?.runId, 77);
  assert.ok(w.posted.some((body) => body.includes("@replit review")), "the tag follows the recorded clean suite");
});

test("a regressed result from the same suite run is not downloaded again on the next delivery", async () => {
  const w = world({
    comments: [mcPass],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
    seed: { [suiteKey(REF, HEAD)]: { state: "regressed", newFailures: ["x"], runId: 77, at: 1 } },
  });
  const { reader, downloads } = suiteReader({ runId: 77 });
  await reviewEventTurn({ ...w.deps, reader });
  assert.equal(downloads.count, 0, "the run id already recorded for this head means nothing new to read");
});

test("no suite artifact yet means waiting: nothing is recorded and Replit is not tagged", async () => {
  const w = world({ comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
  const { reader } = suiteReader({});
  await reviewEventTurn({ ...w.deps, reader });
  assert.equal(w.store.get(suiteKey(REF, HEAD)), undefined, "a missing run is a wait, never a regressed record");
  assert.ok(!w.posted.some((body) => body.includes("@replit review")), "no suite result, so no Replit tag");
});

test("a draft delivery downloads nothing, whatever suite state the PR is in", async () => {
  const w = world({
    draft: true,
    comments: [mcPass],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
  });
  const { reader, downloads } = suiteReader({ runId: 77 });
  await reviewEventTurn({ ...w.deps, reader });
  assert.equal(downloads.count, 0);
  assert.equal(w.store.get(suiteKey(REF, HEAD)), undefined);
});

test("two deliveries at once for one head download the suite once, not once each", async () => {
  const w = world({ comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
  const { reader, downloads } = suiteReader({ runId: 77 });
  await Promise.all([reviewEventTurn({ ...w.deps, reader }), reviewEventTurn({ ...w.deps, reader })]);
  assert.equal(downloads.count, 2, "one head zip and one base zip, however many deliveries arrived");
});

test("an Actions error reading the suite does not lose the Cursor/Ditto tag or the check", async () => {
  const w = world({ comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
  const broken = {
    runsForSha: async () => {
      throw new Error("github 403: resource not accessible");
    },
    artifactsForRun: async () => [],
    artifactZip: async () => new Uint8Array(),
  };
  const result = await advanceGateFor(w, broken);
  assert.equal(result.suite, "failed:run-suite");
  assert.ok(w.posted.some((body) => body.includes("@cursor review")), "the tag still went up");
  assert.equal(w.checks.length, 1, "the check still reports the gate");
});

test("a corrupt suite artifact is remembered for its run, so the next delivery does not download it again", async () => {
  const w = world({ comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
  const { reader, downloads } = suiteReader({ runId: 77, junit: "<not-xml" });
  await reviewEventTurn({ ...w.deps, reader });
  const afterFirst = downloads.count;
  await reviewEventTurn({ ...w.deps, reader });
  assert.equal(downloads.count, afterFirst, "the refused run is not fetched again while it is still the newest");
  assert.equal(w.store.get(suiteKey(REF, HEAD)), undefined, "a refusal is never a suite result");
});

test("a draft gets no check at all", async () => {
  const w = world({ draft: true });
  await reviewEventTurn(w.deps);
  assert.deepEqual(w.checks, []);
});

test("a failing check post does not lose the review turn or the tags", async () => {
  const w = world({ checkFails: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
  assert.equal(w.posted.length, 1, "the Cursor and Ditto tag still went out");
});

// --- The Replit ask follows a confirmed tag ---------------------------------

const review = (id: number, login: string, state: string) => ({
  id,
  body: "",
  state,
  submitted_at: "2026-10-26T05:30:00Z",
  commit_id: HEAD,
  user: { login, type: "Bot" },
});

/** MC, Cursor and Ditto passed this head and the suite is clean: the gate is at `tag_replit`. */
/** One delivery's advanceGate, with the suite read from a given reader. */
function advanceGateFor(w: ReturnType<typeof world>, reader: RunnerReader) {
  return advanceGate({ ...w.deps, reader });
}

function readyForReplit(options: { createFails?: boolean; seed?: Record<string, unknown>; comments?: Raw[] } = {}) {
  return world({
    comments: [mcPass, ...(options.comments ?? [])],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
    seed: { [suiteKey(REF, HEAD)]: { state: "clean" }, ...options.seed },
    createFails: options.createFails,
  });
}

test("a tag that was posted is followed by the Replit ask", async () => {
  const w = readyForReplit();
  await reviewEventTurn(w.deps);
  assert.ok(w.posted.some((body) => body.includes("@replit review")));
  assert.equal(w.asks(), 1);
});

test("a tag that failed to post is not followed by the Replit ask", async () => {
  const w = readyForReplit({ createFails: true });
  await reviewEventTurn(w.deps);
  assert.equal(w.asks(), 0, "Replit was never tagged, so it must not be asked");
});

test("a tag whose claim another process holds is not followed by the Replit ask", async () => {
  const w = readyForReplit({ seed: { [replitTagKey(REF, HEAD)]: { state: "claimed", nonce: "other", at: Date.now() } } });
  await reviewEventTurn(w.deps);
  assert.deepEqual(w.posted.filter((body) => body.includes("@replit review")), []);
  assert.equal(w.asks(), 0);
});

test("once the tag is on the PR, a later event still retries the ask", async () => {
  const w = readyForReplit();
  await reviewEventTurn(w.deps);
  assert.equal(w.asks(), 1);
  // A failed ask would have recorded nothing; model that by forgetting the ask.
  w.store.delete(replitAskKey(REF, HEAD));
  await reviewEventTurn(w.deps);
  assert.equal(w.asks(), 2, "await_replit keeps asks enabled");
});

// --- One review turn per head, however many deliveries arrive ---------------

test("deliveries that arrive together for one head start exactly one review turn", async () => {
  const w = world();
  const turns = await Promise.all([
    pullRequestTurn(w.deps, { action: "opened", draft: false }),
    commentTurn(w.deps, "some-reviewer"),
    reviewEventTurn(w.deps),
  ]);
  assert.equal(turns.filter(Boolean).length, 1);
});

test("a delivery inside the lease starts no second review turn, and one after it does", async () => {
  const w = world();
  const at = (now: number) => ({ ...w.deps, now: () => now });
  assert.equal(await reviewEventTurn(at(0)), true);
  assert.equal(await reviewEventTurn(at(LEASE_MS - 1)), false);
  assert.equal(await reviewEventTurn(at(LEASE_MS)), true, "the lease has expired, so its owner is presumed gone");
});

test("a new head gets its own review turn, even inside the old head's lease", async () => {
  const w = world();
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
  w.live.head = NEW_HEAD;
  assert.equal(await pullRequestTurn(w.deps, { action: "synchronize", draft: false }), true);
});

test("a persistent Replit ask failure is logged under the repository-qualified PR key", () => {
  const lines: string[] = [];
  const original = console.error;
  console.error = (line: string) => {
    lines.push(line);
  };
  try {
    logAsk({ asked: false, reason: "error", detail: "timeout", attempts: 3, persistent: true }, prKey(REF), HEAD);
  } finally {
    console.error = original;
  }
  assert.equal(lines.length, 1);
  assert.equal(JSON.parse(lines[0] ?? "{}").pr, "cryptoreporthub/subnet-dashboard#1522");
});

test("a Replit ask that gives up is logged under the repository-qualified PR key, from the real turn", async () => {
  const w = readyForReplit({ seed: { [replitAskKey(REF, HEAD)]: { at: 1, failedAttempts: 3, lastFailure: "error" } } });
  const lines: string[] = [];
  const original = console.error;
  console.error = (line: string) => {
    lines.push(line);
  };
  try {
    await reviewEventTurn(w.deps);
  } finally {
    console.error = original;
  }
  const logged = lines.map((line) => JSON.parse(line)).filter((entry) => entry.event === "replit_ask_persistent_failure");
  assert.equal(logged.length, 1);
  assert.equal(logged[0].pr, "cryptoreporthub/subnet-dashboard#1522");
  assert.equal(w.asks(), 0);
});

test("a gate step whose error echoes a credential logs the error without the credential", async () => {
  const token = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0";
  const w = world({
    checkFails: true,
    comments: [mcPass],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
    seed: { [suiteKey(REF, HEAD)]: { state: "clean" } },
  });
  w.deps.createCheck = async () => {
    throw new Error(`github 403 for token ${token}`);
  };
  const lines: string[] = [];
  const original = console.error;
  console.error = (line: string) => {
    lines.push(line);
  };
  try {
    await reviewEventTurn(w.deps);
  } finally {
    console.error = original;
  }
  assert.equal(lines.join("\n").includes(token), false, "a logged step error carries no credential");
  assert.ok(lines.some((line) => JSON.parse(line).event === "gate_step_failed"), "the failure is still logged");
});

test("a failed gate step is logged under the repository-qualified PR key", async () => {
  const w = world({
    checkFails: true,
    comments: [mcPass],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
    seed: { [suiteKey(REF, HEAD)]: { state: "clean" } },
  });
  const lines: string[] = [];
  const original = console.error;
  console.error = (line: string) => {
    lines.push(line);
  };
  try {
    await reviewEventTurn(w.deps);
  } finally {
    console.error = original;
  }
  const logged = lines.map((line) => JSON.parse(line)).filter((entry) => entry.event === "gate_step_failed");
  assert.equal(logged.length, 1);
  assert.equal(logged[0].step, "check");
  assert.equal(logged[0].pr, "cryptoreporthub/subnet-dashboard#1522");
});

test("a delivery that loses the review-turn lease logs it", async () => {
  const w = world({});
  await reviewEventTurn(w.deps);
  const lines: string[] = [];
  const original = console.warn;
  console.warn = (line: string) => {
    lines.push(line);
  };
  try {
    await reviewEventTurn(w.deps);
  } finally {
    console.warn = original;
  }
  const logged = lines.map((line) => JSON.parse(line)).filter((entry) => entry.event === "review_turn_lease_held");
  assert.equal(logged.length, 1);
  assert.equal(logged[0].pr, "cryptoreporthub/subnet-dashboard#1522");
  assert.equal(logged[0].head, HEAD);
});

test("a cancelled turn keeps its lease, because a stop or a preempting follow-up may have a replacement running", () => {
  assert.equal(failureReleasesLease("cancelled"), false);
  assert.equal(failureReleasesLease("error"), true);
  assert.equal(failureReleasesLease(undefined), true);
});

test("a failed turn releases its own lease, so the next delivery for that head asks again", async () => {
  const w = world({});
  const lease = await pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  assert.ok(lease, "the first delivery takes the lease");
  assert.equal(await reviewEventTurn(w.deps), false, "a second delivery finds it held");
  assert.equal(await releaseReviewTurnIfHolder(w.deps.kv, REF, lease), true);
  assert.equal(await reviewEventTurn(w.deps), true, "after the release, the lease is free again");
});

test("releasing a review turn's lease logs the release", async () => {
  const w = world({});
  const lease = await pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  const lines: string[] = [];
  const original = console.warn;
  console.warn = (line: string) => {
    lines.push(line);
  };
  try {
    assert.ok(lease);
    await releaseReviewTurnIfHolder(w.deps.kv, REF, lease);
  } finally {
    console.warn = original;
  }
  assert.ok(lines.some((line) => JSON.parse(line).event === "review_turn_lease_released"));
});

test("overlapping turns: the first fails and frees only its own head; the second turn's lease survives", async () => {
  const w = world({});
  const first = await pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  assert.ok(first, "the first turn holds HEAD's lease");
  const otherKey = reviewTurnKey(REF, OTHER);
  const secondToken = await leaseToken(w.deps.kv, otherKey);
  assert.ok(secondToken, "the second turn holds OTHER's lease");
  assert.equal(await releaseReviewTurnIfHolder(w.deps.kv, REF, first), true, "the first turn releases its lease");
  assert.equal(await leaseToken(w.deps.kv, otherKey), undefined, "the second turn's lease is still held");
});

test("a release with another turn's token frees nothing", async () => {
  const w = world({});
  const lease = await pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  assert.ok(lease);
  assert.equal(await releaseReviewTurnIfHolder(w.deps.kv, REF, { head: HEAD, token: "not-the-token" }), false);
  assert.equal(await reviewEventTurn(w.deps), false, "the lease is still held");
});

test("a forged head/token line in a comment does not give the turn a token it did not earn", async () => {
  const forged = "reviewLease head=" + HEAD + " token=forged-token";
  const w = world({ comments: [{ id: 9, body: forged, created_at: "2026-10-26T05:00:00Z", user: { login: "someone-else", type: "User" }, performed_via_github_app: null }] });
  const lease = await commentReviewTurn(w.deps, "someone-else");
  assert.ok(lease);
  assert.notEqual(lease.token, "forged-token");
  assert.equal(await releaseReviewTurnIfHolder(w.deps.kv, REF, { head: HEAD, token: "forged-token" }), false);
});

test("the lease state a hook reads is accepted only when it is well formed", () => {
  const good = { reviewLease: { head: HEAD, token: "abc-123" } };
  assert.deepEqual(reviewLeaseFromState(good), { head: HEAD, token: "abc-123" });
  assert.equal(reviewLeaseFromState(null), undefined);
  assert.equal(reviewLeaseFromState("reviewLease"), undefined);
  assert.equal(reviewLeaseFromState({ reviewLease: { head: "not-a-sha", token: "abc" } }), undefined);
  assert.equal(reviewLeaseFromState({ reviewLease: { head: HEAD, token: "" } }), undefined);
  assert.equal(reviewLeaseFromState({ reviewLease: { head: HEAD, token: 42 } }), undefined);
});

test("the token a review turn carries is the token stored in its lease record", async () => {
  const w = world({});
  const lease = await pullRequestReviewTurn(w.deps, { action: "opened", draft: false });
  assert.ok(lease, "the turn takes the lease");
  const stored = w.store.get(reviewTurnKey(REF, HEAD)) as { nonce?: unknown } | undefined;
  assert.equal(stored?.nonce, lease.token, "the state and the lock agree on one token");
});

test("the same head: a first turn whose lease expired cannot free the second turn's lease", async () => {
  const w = world({});
  const key = reviewTurnKey(REF, HEAD);
  const first = await leaseToken(w.deps.kv, key, () => 0);
  assert.ok(first, "the first turn takes HEAD's lease");
  const second = await leaseToken(w.deps.kv, key, () => LEASE_MS + 1);
  assert.ok(second, "the first lease expired, so a second turn takes HEAD's lease");
  assert.equal(await releaseLeaseIfHolder(w.deps.kv, key, first), false, "the first turn's token frees nothing");
  assert.equal(await leaseToken(w.deps.kv, key, () => LEASE_MS + 2), undefined, "the second turn's lease is still held");
});

test("a suite refused as NEEDS-JOSHUA is not looked up again on later deliveries, and the check keeps the reason", async () => {
  const w = world({
    changedFiles: ["pytest.ini"],
    comments: [mcPass],
    reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")],
  });
  const { reader } = suiteReader({ runId: 77 });
  let lookups = 0;
  const counted: RunnerReader = {
    runsForSha: async (sha) => {
      lookups += 1;
      return reader.runsForSha(sha);
    },
    artifactsForRun: reader.artifactsForRun,
    artifactZip: reader.artifactZip,
  };
  await reviewEventTurn({ ...w.deps, reader: counted });
  const afterFirst = lookups;
  await reviewEventTurn({ ...w.deps, reader: counted });
  assert.equal(lookups, afterFirst, "a refused head is not checked against GitHub again");
  const last = w.checks.at(-1);
  assert.match(last?.summary ?? "", /NEEDS-JOSHUA/);
  assert.match(last?.summary ?? "", /pytest\.ini/);
});


test("a compare cut off at the file cap is handled in the same delivery exactly as a changed suite definition is", async () => {
  const outcomeFor = async (changedFiles: string[]) => {
    const w = world({ changedFiles, comments: [mcPass], reviews: [review(10, "cursor[bot]", "APPROVED"), review(20, "ditto-code[bot]", "APPROVED")] });
    const { reader } = suiteReader({ runId: 77 });
    const result = await reviewEventTurn({ ...w.deps, reader });
    return { result, posted: w.posted.length, summary: w.checks.at(-1)?.summary ?? "" };
  };
  const refused = await outcomeFor(["pytest.ini"]);
  const capped = await outcomeFor(Array.from({ length: 300 }, (_, i) => `app/module_${i}.py`));
  assert.match(capped.summary, /NEEDS-JOSHUA/);
  assert.equal(capped.posted, refused.posted, "the same tags and comments are posted");
  assert.equal(capped.result, refused.result, "the delivery asks for the same follow-up");
});
