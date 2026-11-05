import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import postVerdict from "../bot/tools/post_verdict.js";
import { collectPinnedVerdicts } from "../bot/lib/verdicts.js";
import { readGateFixture, readPrFixture } from "../bot/lib/fixtures.js";
import { redactSecrets } from "../bot/lib/redact.js";

/**
 * The eval session path, without a model.
 *
 * `agent-sdk eval` needs a Cursor credential to boot the channel, so this
 * exercises the part that would otherwise be unverified: an eval session reads
 * `pr.json` / `gate.json` from its workspace, and `post_verdict` must not post.
 * Those are the two assumptions every case in `evals/review-gate.eval.ts`
 * depends on.
 */

async function workspaceWith(files: Record<string, string>): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "review-gate-"));
  for (const [name, body] of Object.entries(files)) {
    await writeFile(join(dir, name), body, "utf8");
  }
  return dir;
}

const PR = {
  number: 1515,
  title: "t",
  url: "u",
  headSha: "e001169a5ef03ef62660e26a902f8ac748c14433",
  baseSha: "882980b817986fdcd2766fb18d46525b8e1955fd",
  draft: false,
  files: ["internal/council/resolver.py"],
};

const GATE = {
  headSha: PR.headSha,
  mc: "missing",
  cursor: "PASS",
  ditto: "missing",
  replit: "missing",
  suite: "missing",
  replitTagged: false,
  next: "review",
};

test("an eval workspace yields the pinned PR", async () => {
  const dir = await workspaceWith({ "pr.json": JSON.stringify(PR) });
  const pr = await readPrFixture(dir);
  assert.equal(pr?.headSha, PR.headSha);
  assert.deepEqual(pr?.files, PR.files);
});

test("an eval workspace yields the pinned gate state", async () => {
  const dir = await workspaceWith({ "gate.json": JSON.stringify(GATE) });
  const gate = await readGateFixture(dir);
  assert.equal(gate?.next, "review");
  assert.equal(gate?.cursor, "PASS");
});

test("a workspace with no fixtures returns undefined rather than throwing", async () => {
  const dir = await workspaceWith({});
  assert.equal(await readPrFixture(dir), undefined);
  assert.equal(await readGateFixture(dir), undefined);
});

test("a malformed fixture fails loudly: a broken case must not run as one that seeded nothing", async () => {
  const dir = await workspaceWith({ "pr.json": "{not json" });
  await assert.rejects(readPrFixture(dir));
});

const VERDICT = {
  headSha: "a".repeat(40),
  verdict: "PASS" as const,
  body: "Looks right.",
  skills: [{ skill: "adversarial-review", used: true, note: "ran" }],
};

/** `defineTool` types `execute` for the SDK's host; the test supplies its own context. */
const execute = postVerdict.execute as unknown as (input: unknown, ctx: unknown) => Promise<unknown>;

/** A tool context that fails the test if the tool reaches for GitHub. */
function contextFor(purpose: "eval" | "live"): unknown {
  return {
    session: { purpose, continuationKey: undefined },
    host: {
      github: {
        getOctokit: async () => {
          throw new Error("reached GitHub");
        },
      },
    },
  };
}

test("post_verdict in an eval session posts nothing and never reaches GitHub", async () => {
  const result = await execute(VERDICT, contextFor("eval"));
  assert.deepEqual(result, { posted: false, reason: "eval", verdict: "PASS" });
});

test("the same call outside an eval is not short-circuited, so the guard above is the eval check", async () => {
  await assert.rejects(execute(VERDICT, contextFor("live")), /GitHub pull request session/);
});

// --- A blocking finding can never ship under a PASS ----------------------------

for (const kind of ["never-expires", "overflow", "aborts-cycle", "poisons-later-row"]) {
  test(`a PASS that declares a '${kind}' finding is refused, in an eval and live`, async () => {
    for (const purpose of ["eval", "live"] as const) {
      const result = await execute({ ...VERDICT, blocking: [kind] }, contextFor(purpose));
      assert.deepEqual(result, { posted: false, reason: "pass-with-blocking-finding", verdict: "PASS", blocking: [kind] }, purpose);
    }
  });
}

test("the same finding under MODIFY or FAIL goes through, so the model can resubmit", async () => {
  for (const verdict of ["MODIFY", "FAIL"] as const) {
    const result = await execute({ ...VERDICT, verdict, blocking: ["overflow"] }, contextFor("eval"));
    assert.deepEqual(result, { posted: false, reason: "eval", verdict });
  }
});

test("a PASS that declares no blocking finding is not refused", async () => {
  assert.deepEqual(await execute({ ...VERDICT, blocking: [] }, contextFor("eval")), { posted: false, reason: "eval", verdict: "PASS" });
});

test("Joshua's own PASS is never read as a Replit verdict", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      {
        id: 1,
        body: `MC: **PASS** at \`${PR.headSha}\``,
        createdAt: "2026-10-26T04:00:00Z",
        user: { login: "cryptoreporthub", type: "User" },
        performedViaGithubApp: null,
      },
    ],
  });
  // Dropped: an owner-account comment only counts as Replit when its body says
  // so, otherwise Joshua's own words would satisfy the Replit gate step.
  assert.deepEqual(pinned, []);
});

test("an owner-account comment naming Replit is a Replit verdict", () => {
  const pinned = collectPinnedVerdicts({
    reviews: [],
    comments: [
      {
        id: 2,
        body: `Replit: **PASS** at ${PR.headSha}`,
        createdAt: "2026-10-26T04:00:00Z",
        user: { login: "cryptoreporthub", type: "User" },
        performedViaGithubApp: null,
      },
    ],
  });
  assert.equal(pinned.length, 1);
  assert.equal(pinned[0]?.reviewer, "replit");
  assert.equal(pinned[0]?.verdict, "PASS");
});

test("the secret-echo leak is scrubbed before it could reach a comment", () => {
  const { text } = redactSecrets("GITHUB_TOKEN=ghp_ZZZZsecretsecretsecret0123456789");
  assert.equal(text.includes("ghp_ZZZZ"), false);
});
